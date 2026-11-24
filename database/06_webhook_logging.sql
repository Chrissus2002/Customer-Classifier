-- =====================================================================
-- File: database/06_webhook_logging.sql
-- Purpose: Webhook logging and observability layer
-- Complete audit trail for webhook ingestion pipeline
-- =====================================================================

-- =====================================================================
-- WEBHOOK LOGGING TABLES
-- =====================================================================

-- Webhook Logs - Initial capture of every webhook
CREATE TABLE IF NOT EXISTS public.webhook_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT REFERENCES public.tenants(tenant_id),

  -- Request details
  method TEXT,
  url TEXT,
  headers JSONB,
  payload JSONB NOT NULL,

  -- Processing status
  processed BOOLEAN DEFAULT false,
  processed_at TIMESTAMPTZ,
  error TEXT,

  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_webhook_logs_tenant ON public.webhook_logs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_logs_unprocessed ON public.webhook_logs(created_at) WHERE processed = false;

COMMENT ON TABLE public.webhook_logs IS 'Complete log of all incoming webhooks - enables debugging and replay';
COMMENT ON COLUMN public.webhook_logs.processed IS 'True when webhook has been processed to bronze layer';
COMMENT ON COLUMN public.webhook_logs.error IS 'Error message if processing failed';

-- Webhook Processing Log - Detailed processing history
CREATE TABLE IF NOT EXISTS public.webhook_processing_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  webhook_id UUID REFERENCES public.webhook_logs(id),
  tenant_id BIGINT,

  action TEXT NOT NULL,  -- 'received', 'processed', 'failed', 'duplicate', 'skipped'
  reason TEXT,           -- human-readable explanation
  details JSONB,         -- additional context (extracted fields, error details)

  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_webhook_processing_webhook ON public.webhook_processing_log(webhook_id);
CREATE INDEX IF NOT EXISTS idx_webhook_processing_action ON public.webhook_processing_log(action, created_at DESC);

COMMENT ON TABLE public.webhook_processing_log IS 'Detailed audit trail of webhook processing steps';
COMMENT ON COLUMN public.webhook_processing_log.action IS 'Processing action: received, processed, failed, duplicate, skipped';

-- =====================================================================
-- TRIGGER FUNCTION: webhook_logs → bronze.wati_messages
-- =====================================================================

CREATE OR REPLACE FUNCTION public.process_webhook_to_bronze()
RETURNS TRIGGER AS $$
DECLARE
  v_contact_id TEXT;
  v_message_id TEXT;
  v_conversation_id TEXT;
BEGIN
  -- Extract contact ID from payload (try multiple field names)
  v_contact_id := COALESCE(
    NEW.payload->>'waId',
    NEW.payload->>'wAid',
    NEW.payload->>'whatsappNumber'
  );

  -- Extract or generate message ID
  -- gen_random_uuid() fallback avoids UNIQUE collisions on bronze.wati_messages(tenant_id, wati_message_id)
  v_message_id := COALESCE(
    NEW.payload->>'id',
    NEW.payload->>'messageId',
    gen_random_uuid()::TEXT
  );

  v_conversation_id := COALESCE(NEW.payload->>'conversationId', 'Conversation had no ID');

  -- Insert into bronze layer
  INSERT INTO bronze.wati_messages (
    tenant_id,
    wati_contact_id,
    raw_data,
    batch_id,  -- NULL for webhooks
    wati_message_id,
    conversation_id
  ) VALUES (
    NEW.tenant_id,
    v_contact_id,
    NEW.payload,
    NULL,
    v_message_id,
    v_conversation_id
  );

  -- Mark webhook as processed
  UPDATE public.webhook_logs
  SET processed = true, processed_at = NOW()
  WHERE id = NEW.id;

  -- Log processing step
  INSERT INTO public.webhook_processing_log (webhook_id, tenant_id, action, details)
  VALUES (NEW.id, NEW.tenant_id, 'processed', jsonb_build_object(
    'contact_id', v_contact_id,
    'message_id', v_message_id
  ));

  RETURN NEW;

EXCEPTION WHEN OTHERS THEN
  -- Log failure but don't block
  UPDATE public.webhook_logs
  SET error = SQLERRM
  WHERE id = NEW.id;

  INSERT INTO public.webhook_processing_log (webhook_id, tenant_id, action, reason, details)
  VALUES (NEW.id, NEW.tenant_id, 'failed', SQLERRM, jsonb_build_object('sqlstate', SQLSTATE));

  RETURN NEW;  -- Don't raise, allow webhook to complete
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION public.process_webhook_to_bronze IS 'Trigger function: processes webhook_logs into bronze.wati_messages';

-- Create trigger
DROP TRIGGER IF EXISTS process_webhook_logs ON public.webhook_logs;

CREATE TRIGGER process_webhook_logs
AFTER INSERT ON public.webhook_logs
FOR EACH ROW
EXECUTE FUNCTION public.process_webhook_to_bronze();

-- =====================================================================
-- HEALTH CHECK FUNCTIONS
-- =====================================================================

-- Webhook Health Check
CREATE OR REPLACE FUNCTION public.check_webhook_health(hours INTEGER DEFAULT 24)
RETURNS TABLE (
  tenant_id BIGINT,
  total_received BIGINT,
  total_processed BIGINT,
  total_failed BIGINT,
  processing_rate NUMERIC,
  avg_processing_time_ms NUMERIC
) AS $$
BEGIN
  RETURN QUERY
  SELECT
    w.tenant_id,
    COUNT(*) as total_received,
    COUNT(*) FILTER (WHERE w.processed = true) as total_processed,
    COUNT(*) FILTER (WHERE w.error IS NOT NULL) as total_failed,
    ROUND(100.0 * COUNT(*) FILTER (WHERE w.processed) / NULLIF(COUNT(*), 0), 2) as processing_rate,
    ROUND(AVG(EXTRACT(EPOCH FROM (w.processed_at - w.created_at)) * 1000) FILTER (WHERE w.processed), 2) as avg_processing_time_ms
  FROM public.webhook_logs w
  WHERE w.created_at > NOW() - (hours || ' hours')::INTERVAL
  GROUP BY w.tenant_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION public.check_webhook_health IS 'Health check for webhook processing - returns metrics per tenant';

-- Webhook Debug Function
CREATE OR REPLACE FUNCTION public.debug_webhook(p_webhook_id UUID)
RETURNS TABLE (
  step TEXT,
  event_timestamp TIMESTAMPTZ,
  action TEXT,
  details JSONB
) AS $$
BEGIN
  RETURN QUERY
  SELECT * FROM (
    -- Initial receipt
    SELECT
      'received'::TEXT as step,
      w.created_at as event_timestamp,
      'webhook_logged'::TEXT as action,
      jsonb_build_object(
        'method', w.method,
        'url', w.url,
        'processed', w.processed,
        'error', w.error
      ) as details
    FROM public.webhook_logs w
    WHERE w.id = p_webhook_id

    UNION ALL

    -- Processing steps
    SELECT
      'processing'::TEXT as step,
      pl.created_at as event_timestamp,
      pl.action,
      pl.details
    FROM public.webhook_processing_log pl
    WHERE pl.webhook_id = p_webhook_id
  ) sub
  ORDER BY event_timestamp;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION public.debug_webhook IS 'Debug a specific webhook - shows complete processing timeline';

-- Duplicate Contact Detection
CREATE OR REPLACE FUNCTION public.detect_duplicate_contacts()
RETURNS TABLE(
  tenant_id BIGINT,
  identity_key TEXT,
  duplicate_count BIGINT,
  contact_ids UUID[]
) AS $$
BEGIN
  RETURN QUERY
  SELECT
    c.tenant_id,
    COALESCE(c.phone_identity_key, 'legacy:' || c.phone_normalized) AS identity_key,
    COUNT(*) as duplicate_count,
    ARRAY_AGG(c.contact_id) as contact_ids
  FROM silver.contacts c
  WHERE c.is_canonical = true
  GROUP BY c.tenant_id, COALESCE(c.phone_identity_key, 'legacy:' || c.phone_normalized)
  HAVING COUNT(*) > 1;

  IF FOUND THEN
    RAISE WARNING 'DUPLICATE CONTACTS DETECTED! Check health_checks.log';
  END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION public.detect_duplicate_contacts IS 'Health check: detects duplicate contacts using phone_identity_key when present, otherwise falls back to legacy phone_normalized';

-- =====================================================================
-- MONITORING VIEWS
-- =====================================================================

-- Webhook Processing Status
CREATE OR REPLACE VIEW public.webhook_processing_status AS
SELECT
  tenant_id,
  DATE_TRUNC('hour', created_at) as hour,
  COUNT(*) as received,
  COUNT(*) FILTER (WHERE processed) as processed,
  COUNT(*) FILTER (WHERE error IS NOT NULL) as failed,
  COUNT(*) FILTER (WHERE NOT processed AND error IS NULL) as pending
FROM public.webhook_logs
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY tenant_id, DATE_TRUNC('hour', created_at)
ORDER BY hour DESC;

COMMENT ON VIEW public.webhook_processing_status IS 'Real-time monitoring view - hourly webhook processing status';

-- =====================================================================
-- USAGE EXAMPLES
-- =====================================================================

-- Check webhook health for last 24 hours:
-- SELECT * FROM public.check_webhook_health();

-- Check webhook health for last hour:
-- SELECT * FROM public.check_webhook_health(1);

-- Debug a specific webhook:
-- SELECT * FROM public.debug_webhook('webhook-uuid-here');

-- Check for duplicate contacts:
-- SELECT * FROM public.detect_duplicate_contacts();

-- View webhook processing status:
-- SELECT * FROM public.webhook_processing_status;
