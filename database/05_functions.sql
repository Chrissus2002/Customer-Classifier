-- =====================================================================
-- File: database/05_functions.sql
-- Purpose: Processing functions for Bronze→Silver transformation
-- =====================================================================

-- =====================================================================
-- MESSAGE DIRECTION INFERENCE
-- =====================================================================
-- Single source of truth for deriving direction ('inbound' | 'outbound' |
-- 'system') from a Wati message payload. Used by BOTH the webhook trigger
-- (bronze.transform_webhook_to_silver) and the batch processor
-- (bronze.process_messages_to_silver) so they can't drift.
--
-- Rules, in order (most authoritative first):
--
--   1. eventType is the most reliable signal when Wati sets it:
--      - 'broadcastMessage'        → outbound (business broadcast, often
--                                    has owner=null tricking rule 4)
--      - 'templateMessageSent_v2'  → outbound (business-sent template)
--      - 'sessionMessageSent'      → outbound (business session message)
--      - 'sentMessageREAD'         → outbound (read receipt for sent msg)
--      - 'sentMessageDELIVERED_v2' → outbound (delivery receipt)
--      - 'ticket'                  → system (chat/ticket state events)
--
--      Discovered 2026-04-08: without the broadcastMessage check, ~14k
--      broadcasts for tenant YOUR_TENANT_ID were mislabeled as 'inbound' because
--      Wati reports them with owner=null. The eventType field was in
--      raw_data all along but no rule consulted it.
--
--   2. wati_contact_id IS NULL            → outbound (legacy webhook path —
--                                           webhooks omit waId for
--                                           business-sent messages)
--   3. type IN ('0'..'5')                 → system (Wati status/event codes)
--   4. owner in ('true','True','1','TRUE')→ outbound (business sent it)
--   5. otherwise                          → inbound
--
-- Keep the owner-value set permissive: real-world data today has only
-- lowercase 'true'/'false', but if Wati ever changes formatting we
-- don't want to silently misclassify.

CREATE OR REPLACE FUNCTION bronze.infer_message_direction(
  p_raw_data JSONB,
  p_wati_contact_id TEXT
) RETURNS TEXT AS $$
BEGIN
  -- Rule 1: eventType is the most authoritative signal when set.
  IF p_raw_data->>'eventType' IN (
    'broadcastMessage',
    'templateMessageSent_v2',
    'sessionMessageSent',
    'sentMessageREAD',
    'sentMessageDELIVERED_v2'
  ) THEN
    RETURN 'outbound';
  END IF;

  IF p_raw_data->>'eventType' = 'ticket' THEN
    RETURN 'system';
  END IF;

  -- Rule 2: legacy path — webhooks omit waId for business-sent messages.
  IF p_wati_contact_id IS NULL THEN
    RETURN 'outbound';
  END IF;

  -- Rule 3: numeric type codes are system/event messages.
  IF p_raw_data->>'type' IN ('0', '1', '2', '3', '4', '5') THEN
    RETURN 'system';
  END IF;

  -- Rule 4: explicit owner flag from Wati's own labeling.
  IF p_raw_data->>'owner' IN ('true', 'True', '1', 'TRUE') THEN
    RETURN 'outbound';
  END IF;

  -- Default: customer message.
  RETURN 'inbound';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION bronze.infer_message_direction IS
  'Derive direction (inbound/outbound/system) from a Wati message payload. Single source of truth for both webhook trigger and batch processor. eventType takes precedence because Wati reports broadcasts with owner=null.';

-- =====================================================================
-- PHONE NORMALIZATION FUNCTION
-- =====================================================================

CREATE OR REPLACE FUNCTION bronze.normalize_phone(phone TEXT)
RETURNS TEXT AS $$
BEGIN
  IF phone IS NULL THEN
    RETURN NULL;
  END IF;

  -- Strip all non-digits
  phone := REGEXP_REPLACE(phone, '[^0-9]', '', 'g');

  -- Fix Mexican mobile numbers: 52XXXXXXXXXX → 521XXXXXXXXXX
  -- If starts with '52' but third digit is not '1', insert '1' after '52'
  IF LEFT(phone, 2) = '52' AND LEFT(phone, 3) != '521' THEN
    phone := '521' || SUBSTRING(phone FROM 3);
  END IF;

  RETURN phone;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION bronze.normalize_phone IS 'Legacy Wati-lookup normalizer: strips non-digits, then fixes Mexican mobile numbers (52X → 521). Kept for compatibility while dialo-5 shadow identity fields are populated by the Python parser.';

CREATE OR REPLACE FUNCTION bronze.count_distinct_normalized_phones(p_phones TEXT[])
RETURNS INTEGER AS $$
BEGIN
  RETURN (
    SELECT COUNT(DISTINCT normalized_phone)
    FROM (
      SELECT bronze.normalize_phone(phone) AS normalized_phone
      FROM unnest(COALESCE(p_phones, ARRAY[]::TEXT[])) AS phone
    ) normalized
    WHERE normalized_phone IS NOT NULL
  );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION bronze.count_distinct_normalized_phones IS
  'Count distinct legacy normalized phone numbers using bronze.normalize_phone(). Retained for compatibility; exact drift now uses the Python phone_identity parser.';

-- =====================================================================
-- MANUAL CONTACT MERGE FUNCTION
-- =====================================================================

CREATE OR REPLACE FUNCTION silver.merge_contacts(
  p_tenant_id BIGINT,
  p_source_contact_id UUID,
  p_target_contact_id UUID
) RETURNS JSONB AS $$
DECLARE
  v_source silver.contacts;
  v_target silver.contacts;
  v_messages_reassigned INTEGER;
  v_traits_reassigned INTEGER := 0;
  v_traits_reconciled INTEGER := 0;
  v_merge_id UUID;
BEGIN
  -- 1. Lock both contact rows (prevent concurrent modifications)
  SELECT * INTO v_source FROM silver.contacts
  WHERE contact_id = p_source_contact_id AND tenant_id = p_tenant_id
  FOR UPDATE;

  SELECT * INTO v_target FROM silver.contacts
  WHERE contact_id = p_target_contact_id AND tenant_id = p_tenant_id
  FOR UPDATE;

  IF v_source IS NULL OR v_target IS NULL THEN
    RAISE EXCEPTION 'Contact not found';
  END IF;

  IF NOT v_source.is_canonical THEN
    RAISE EXCEPTION 'Source contact already merged';
  END IF;

  -- 2. Merge fields into target (prefer longer, non-null)
  UPDATE silver.contacts SET
    name = CASE
      WHEN LENGTH(v_source.name) > LENGTH(name) THEN v_source.name
      WHEN name IS NULL THEN v_source.name
      ELSE name
    END,
    source = COALESCE(source, v_source.source),
    phone_raw = COALESCE(phone_raw, v_source.phone_raw),
    phone_raw_primary = COALESCE(phone_raw_primary, v_source.phone_raw_primary),
    phone_identity_key = COALESCE(phone_identity_key, v_source.phone_identity_key),
    phone_e164 = COALESCE(phone_e164, v_source.phone_e164),
    normalization_status = COALESCE(normalization_status, v_source.normalization_status),
    normalization_region = COALESCE(normalization_region, v_source.normalization_region),
    wati_lookup_phone = COALESCE(wati_lookup_phone, v_source.wati_lookup_phone),
    wati_contact_id = COALESCE(wati_contact_id, v_source.wati_contact_id),
    updated_at = NOW()
  WHERE contact_id = p_target_contact_id;

  -- 3. Reassign all messages from source → target
  UPDATE silver.messages
  SET contact_id = p_target_contact_id
  WHERE contact_id = p_source_contact_id AND tenant_id = p_tenant_id;

  GET DIAGNOSTICS v_messages_reassigned = ROW_COUNT;

  UPDATE silver.contact_wati_keys
  SET
    contact_id = p_target_contact_id,
    is_primary = FALSE,
    last_seen_at = NOW()
  WHERE contact_id = p_source_contact_id
    AND tenant_id = p_tenant_id;

  -- 3b. Reconcile current jbuild trait values from source -> target.
  -- Move rows where the target has no value for that trait yet.
  UPDATE silver.contact_trait_values source_values
  SET
    contact_id = p_target_contact_id,
    updated_at = NOW()
  WHERE source_values.contact_id = p_source_contact_id
    AND source_values.tenant_id = p_tenant_id
    AND NOT EXISTS (
      SELECT 1
      FROM silver.contact_trait_values target_values
      WHERE target_values.tenant_id = p_tenant_id
        AND target_values.contact_id = p_target_contact_id
        AND target_values.trait_id = source_values.trait_id
    );

  GET DIAGNOSTICS v_traits_reassigned = ROW_COUNT;

  -- For conflicts, stronger source wins; same source uses newer resolved_at.
  UPDATE silver.contact_trait_values target_values
  SET
    resolved_value = source_values.resolved_value,
    resolution_source = source_values.resolution_source,
    confidence = source_values.confidence,
    reasoning = source_values.reasoning,
    classifier_version = source_values.classifier_version,
    source_metadata = source_values.source_metadata,
    resolved_at = source_values.resolved_at,
    updated_at = NOW()
  FROM silver.contact_trait_values source_values
  WHERE target_values.tenant_id = p_tenant_id
    AND target_values.contact_id = p_target_contact_id
    AND source_values.tenant_id = p_tenant_id
    AND source_values.contact_id = p_source_contact_id
    AND target_values.trait_id = source_values.trait_id
    AND (
      public.trait_resolution_source_rank(source_values.resolution_source) >
        public.trait_resolution_source_rank(target_values.resolution_source)
      OR (
        public.trait_resolution_source_rank(source_values.resolution_source) =
          public.trait_resolution_source_rank(target_values.resolution_source)
        AND source_values.resolved_at > target_values.resolved_at
      )
    );

  GET DIAGNOSTICS v_traits_reconciled = ROW_COUNT;

  -- Remove source rows that could not be moved after conflict reconciliation.
  DELETE FROM silver.contact_trait_values
  WHERE contact_id = p_source_contact_id
    AND tenant_id = p_tenant_id;

  -- 4. Soft delete source
  UPDATE silver.contacts SET
    is_canonical = false,
    merged_into = p_target_contact_id,
    merged_at = NOW(),
    updated_at = NOW()
  WHERE contact_id = p_source_contact_id;

  -- 5. Log merge to audit
  INSERT INTO audit.contact_merges (
    tenant_id, source_contact_id, target_contact_id,
    reason, messages_reassigned, fields_merged
  ) VALUES (
    p_tenant_id, p_source_contact_id, p_target_contact_id,
    'manual_merge', v_messages_reassigned,
    jsonb_build_object(
      'source_name', v_source.name,
      'target_name', v_target.name,
      'source_url', v_source.source,
      'target_url', v_target.source,
      'trait_rows_reassigned', v_traits_reassigned,
      'trait_rows_reconciled', v_traits_reconciled
    )
  ) RETURNING merge_id INTO v_merge_id;

  -- 6. Log message reassignments (batch insert for efficiency)
  INSERT INTO audit.message_reassignments (merge_id, message_id, old_contact_id, new_contact_id)
  SELECT v_merge_id, message_id, p_source_contact_id, p_target_contact_id
  FROM silver.messages
  WHERE contact_id = p_target_contact_id
    AND tenant_id = p_tenant_id;

  RETURN jsonb_build_object(
    'merge_id', v_merge_id,
    'messages_reassigned', v_messages_reassigned,
    'trait_rows_reassigned', v_traits_reassigned,
    'trait_rows_reconciled', v_traits_reconciled,
    'source_contact_id', p_source_contact_id,
    'target_contact_id', p_target_contact_id
  );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION silver.merge_contacts IS 'Manually merge two contacts - used for admin operations or edge cases';

-- =====================================================================
-- JBUILD TRAIT PRECEDENCE AND ACTIVATION
-- =====================================================================

CREATE OR REPLACE FUNCTION public.trait_resolution_source_rank(p_source TEXT)
RETURNS INTEGER LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  RETURN CASE p_source
    WHEN 'manual' THEN 4
    WHEN 'imported' THEN 3
    WHEN 'rule' THEN 2
    WHEN 'classifier' THEN 1
    ELSE 0
  END;
END;
$$;

COMMENT ON FUNCTION public.trait_resolution_source_rank IS 'Global jbuild current-trait precedence: manual > imported > rule > classifier.';

CREATE OR REPLACE FUNCTION public.activate_trait_classifier_config(
  p_tenant_id BIGINT,
  p_trait_id UUID,
  p_config_id UUID
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  v_config_exists BOOLEAN;
BEGIN
  SELECT TRUE INTO v_config_exists
  FROM public.tenant_trait_classifier_configs
  WHERE tenant_id = p_tenant_id
    AND trait_id = p_trait_id
    AND config_id = p_config_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Trait classifier config % not found for tenant % trait %',
      p_config_id, p_tenant_id, p_trait_id;
  END IF;

  UPDATE public.tenant_trait_classifier_configs
    SET is_active = false
    WHERE tenant_id = p_tenant_id
      AND trait_id = p_trait_id
      AND is_active = true;

  UPDATE public.tenant_trait_classifier_configs
    SET is_active = true, activated_at = COALESCE(activated_at, NOW())
    WHERE config_id = p_config_id
      AND tenant_id = p_tenant_id
      AND trait_id = p_trait_id;
END;
$$;

COMMENT ON FUNCTION public.activate_trait_classifier_config IS 'Atomically swap the active jbuild Trait Classifier config for one tenant+trait.';

CREATE OR REPLACE FUNCTION public.upsert_contact_trait_values(
  p_tenant_id BIGINT,
  p_rows JSONB
) RETURNS JSONB LANGUAGE plpgsql AS $$
DECLARE
  v_row JSONB;
  v_contact silver.contacts;
  v_trait_definition public.tenant_trait_definitions;
  v_contact_id UUID;
  v_trait_id UUID;
  v_resolved_value TEXT;
  v_resolution_source TEXT;
  v_confidence FLOAT;
  v_reasoning TEXT;
  v_classifier_version TEXT;
  v_source_metadata JSONB;
  v_resolved_at TIMESTAMPTZ;
  v_existing silver.contact_trait_values;
  v_inserted INTEGER := 0;
  v_updated INTEGER := 0;
  v_ignored INTEGER := 0;
  v_row_count INTEGER := 0;
BEGIN
  IF p_rows IS NULL OR jsonb_typeof(p_rows) <> 'array' THEN
    RAISE EXCEPTION 'p_rows must be a JSON array';
  END IF;

  FOR v_row IN SELECT * FROM jsonb_array_elements(p_rows)
  LOOP
    v_contact_id := (v_row->>'contact_id')::UUID;
    v_trait_id := (v_row->>'trait_id')::UUID;
    v_resolved_value := NULLIF(v_row->>'resolved_value', '');
    v_resolution_source := v_row->>'resolution_source';
    v_confidence := NULLIF(v_row->>'confidence', '')::FLOAT;
    v_reasoning := v_row->>'reasoning';
    v_classifier_version := v_row->>'classifier_version';
    v_source_metadata := COALESCE(v_row->'source_metadata', '{}'::jsonb);
    v_resolved_at := COALESCE(NULLIF(v_row->>'resolved_at', '')::TIMESTAMPTZ, NOW());

    IF v_resolved_value IS NULL THEN
      RAISE EXCEPTION 'resolved_value is required';
    END IF;

    IF public.trait_resolution_source_rank(v_resolution_source) = 0 THEN
      RAISE EXCEPTION 'Invalid resolution_source: %', v_resolution_source;
    END IF;

    SELECT * INTO v_contact
    FROM silver.contacts
      WHERE tenant_id = p_tenant_id AND contact_id = v_contact_id
      FOR UPDATE;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'Contact % not found for tenant %', v_contact_id, p_tenant_id;
    END IF;

    IF v_contact.is_canonical IS DISTINCT FROM true THEN
      RAISE EXCEPTION 'Contact % is not canonical for tenant %', v_contact_id, p_tenant_id;
    END IF;

    SELECT * INTO v_trait_definition
    FROM public.tenant_trait_definitions
      WHERE tenant_id = p_tenant_id AND trait_id = v_trait_id
      FOR UPDATE;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'Trait % not found for tenant %', v_trait_id, p_tenant_id;
    END IF;

    IF v_trait_definition.value_type = 'enum'
       AND NOT COALESCE(v_trait_definition.allowed_values ? v_resolved_value, false)
    THEN
      RAISE EXCEPTION 'resolved_value % is not allowed for trait %',
        v_resolved_value, v_trait_id;
    END IF;

    IF v_trait_definition.value_type = 'boolean'
       AND v_resolved_value NOT IN ('true', 'false', 'unknown')
    THEN
      RAISE EXCEPTION 'resolved_value % is not a boolean trait value for trait %',
        v_resolved_value, v_trait_id;
    END IF;

    SELECT * INTO v_existing
    FROM silver.contact_trait_values
    WHERE tenant_id = p_tenant_id
      AND contact_id = v_contact_id
      AND trait_id = v_trait_id
    FOR UPDATE;

    IF NOT FOUND THEN
      INSERT INTO silver.contact_trait_values (
        tenant_id,
        contact_id,
        trait_id,
        resolved_value,
        resolution_source,
        confidence,
        reasoning,
        classifier_version,
        source_metadata,
        resolved_at,
        updated_at
      ) VALUES (
        p_tenant_id,
        v_contact_id,
        v_trait_id,
        v_resolved_value,
        v_resolution_source,
        v_confidence,
        v_reasoning,
        v_classifier_version,
        v_source_metadata,
        v_resolved_at,
        NOW()
      )
      ON CONFLICT (tenant_id, contact_id, trait_id) DO NOTHING;

      GET DIAGNOSTICS v_row_count = ROW_COUNT;
      IF v_row_count = 1 THEN
        v_inserted := v_inserted + 1;
        CONTINUE;
      END IF;

      SELECT * INTO v_existing
      FROM silver.contact_trait_values
      WHERE tenant_id = p_tenant_id
        AND contact_id = v_contact_id
        AND trait_id = v_trait_id
      FOR UPDATE;
    END IF;

    IF public.trait_resolution_source_rank(v_resolution_source) >
         public.trait_resolution_source_rank(v_existing.resolution_source)
       OR (
         public.trait_resolution_source_rank(v_resolution_source) =
           public.trait_resolution_source_rank(v_existing.resolution_source)
         AND v_resolved_at >= v_existing.resolved_at
       )
    THEN
      UPDATE silver.contact_trait_values
      SET
        resolved_value = v_resolved_value,
        resolution_source = v_resolution_source,
        confidence = v_confidence,
        reasoning = v_reasoning,
        classifier_version = v_classifier_version,
        source_metadata = v_source_metadata,
        resolved_at = v_resolved_at,
        updated_at = NOW()
      WHERE trait_value_id = v_existing.trait_value_id;

      v_updated := v_updated + 1;
    ELSE
      v_ignored := v_ignored + 1;
    END IF;
  END LOOP;

  RETURN jsonb_build_object(
    'inserted', v_inserted,
    'updated', v_updated,
    'ignored', v_ignored
  );
END;
$$;

COMMENT ON FUNCTION public.upsert_contact_trait_values IS 'Atomically upsert current jbuild trait values while enforcing source precedence.';

-- =====================================================================
-- WEBHOOK PROCESSING TRIGGER FUNCTION (Bronze → Silver)
-- =====================================================================

CREATE OR REPLACE FUNCTION bronze.transform_webhook_to_silver()
RETURNS TRIGGER AS $$
DECLARE
  v_contact_id UUID;
  v_message_direction TEXT;
  v_conversation_id TEXT;
  v_phone_normalized TEXT;
  v_raw_phone TEXT;
  v_tenant_phone_normalized TEXT;
BEGIN
  -- Only process webhooks (batch_id = NULL)
  -- Batch imports call process_to_silver() directly
  v_message_direction := bronze.infer_message_direction(NEW.raw_data, NEW.wati_contact_id);
  v_conversation_id := COALESCE(NEW.raw_data->>'conversationId', NEW.conversation_id, 'Conversation had no ID');

  -- Inbound and session-sent outbound messages carry waId. True delivery/read
  -- receipts do not, so they must resolve back to an existing conversation
  -- contact rather than fabricating a self-contact on the tenant number.
  IF NEW.wati_contact_id IS NOT NULL THEN
    -- Customer/business counterparty phone from waId
    v_raw_phone := NEW.wati_contact_id;
    v_phone_normalized := bronze.normalize_phone(NEW.wati_contact_id);
  ELSE
    SELECT bronze.normalize_phone(wati_phone_number) INTO v_tenant_phone_normalized
    FROM public.tenants
    WHERE tenant_id = NEW.tenant_id;

    SELECT m.contact_id INTO v_contact_id
    FROM silver.messages m
    JOIN silver.contacts c ON c.contact_id = m.contact_id
      AND c.tenant_id = m.tenant_id
    WHERE m.tenant_id = NEW.tenant_id
      AND m.conversation_id = v_conversation_id
      AND (
        v_tenant_phone_normalized IS NULL
        OR c.phone_normalized IS DISTINCT FROM v_tenant_phone_normalized
      )
    ORDER BY m.timestamp DESC, m.created_at DESC
    LIMIT 1;

    IF v_contact_id IS NULL THEN
      INSERT INTO public.webhook_processing_log (tenant_id, action, reason, details)
      VALUES (
        NEW.tenant_id,
        'silver_transform_skipped',
        'outbound message has no waId and no existing conversation contact',
        jsonb_build_object(
          'wati_message_id', NEW.wati_message_id,
          'conversation_id', v_conversation_id,
          'event_type', NEW.raw_data->>'eventType'
        )
      );
      RETURN NEW;
    END IF;
  END IF;

  IF NEW.wati_contact_id IS NOT NULL THEN
    -- UPSERT contact (atomic, race-safe)
    INSERT INTO silver.contacts (
      tenant_id,
      batch_id,
      phone_normalized,
      phone_raw,
      phone_raw_primary,
      name,
      wati_contact_id,
      wati_lookup_phone,
      created_at
    ) VALUES (
      NEW.tenant_id,
      NULL,  -- Webhooks don't have batch_id
      v_phone_normalized,
      v_raw_phone,
      v_raw_phone,
      COALESCE(NEW.raw_data->>'senderName', NEW.raw_data->>'name', NEW.raw_data->>'pushName'),
      NEW.wati_contact_id,
      v_phone_normalized,
      COALESCE(
        (NEW.raw_data->>'created')::TIMESTAMPTZ,
        (NEW.raw_data->>'createdDateTime')::TIMESTAMPTZ,
        NOW()
      )
    )
    ON CONFLICT (tenant_id, phone_normalized)
    DO UPDATE SET
      name = CASE
        WHEN silver.contacts.name IS NULL THEN EXCLUDED.name
        WHEN EXCLUDED.name IS NOT NULL AND LENGTH(EXCLUDED.name) > LENGTH(silver.contacts.name) THEN EXCLUDED.name
        ELSE silver.contacts.name
      END,
      phone_raw = COALESCE(EXCLUDED.phone_raw, silver.contacts.phone_raw),
      phone_raw_primary = COALESCE(EXCLUDED.phone_raw_primary, silver.contacts.phone_raw_primary),
      wati_contact_id = COALESCE(EXCLUDED.wati_contact_id, silver.contacts.wati_contact_id),
      wati_lookup_phone = COALESCE(EXCLUDED.wati_lookup_phone, silver.contacts.wati_lookup_phone),
      updated_at = NOW()
    RETURNING contact_id INTO v_contact_id;
  END IF;

  IF NEW.wati_contact_id IS NOT NULL THEN
    INSERT INTO silver.contact_wati_keys (
      tenant_id,
      contact_id,
      wati_contact_id,
      wati_lookup_phone,
      is_primary,
      last_seen_at
    ) VALUES (
      NEW.tenant_id,
      v_contact_id,
      NEW.wati_contact_id,
      v_phone_normalized,
      TRUE,
      NOW()
    )
    ON CONFLICT (tenant_id, wati_contact_id)
    DO UPDATE SET
      contact_id = EXCLUDED.contact_id,
      wati_lookup_phone = COALESCE(EXCLUDED.wati_lookup_phone, silver.contact_wati_keys.wati_lookup_phone),
      is_primary = EXCLUDED.is_primary,
      last_seen_at = NOW();
  END IF;

  -- Skip text messages with no content (e.g. newContactMessageReceived events)
  IF COALESCE(NEW.raw_data->>'type', 'text') = 'text'
     AND COALESCE(NEW.raw_data->>'text', NEW.raw_data->>'finalText', NEW.raw_data->>'eventDescription') IS NULL THEN
    RETURN NEW;
  END IF;

  -- Insert message (idempotent)
  INSERT INTO silver.messages (
    tenant_id,
    batch_id,
    contact_id,
    wati_message_id,
    text,
    direction,
    message_type,
    timestamp,
    conversation_id
  ) VALUES (
    NEW.tenant_id,
    NULL,  -- Webhooks don't have batch_id
    v_contact_id,
    COALESCE(NEW.raw_data->>'id', NEW.raw_data->>'messageId'),
    COALESCE(NEW.raw_data->>'text', NEW.raw_data->>'finalText', NEW.raw_data->>'eventDescription'),
    v_message_direction,
    COALESCE(NEW.raw_data->>'type', 'text'),
    COALESCE((NEW.raw_data->>'created')::TIMESTAMPTZ, NOW()),
    v_conversation_id
  )
  ON CONFLICT (tenant_id, wati_message_id) DO NOTHING;

  RETURN NEW;

EXCEPTION WHEN OTHERS THEN
  -- Log failure but don't block the bronze insert
  INSERT INTO public.webhook_processing_log (tenant_id, action, reason, details)
  VALUES (NEW.tenant_id, 'silver_transform_failed', SQLERRM, jsonb_build_object(
    'sqlstate', SQLSTATE,
    'wati_contact_id', NEW.wati_contact_id,
    'wati_message_id', NEW.wati_message_id
  ));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION bronze.transform_webhook_to_silver IS 'Trigger function: processes bronze.wati_messages into silver layer (webhooks only)';

-- =====================================================================
-- CREATE TRIGGER: transform_webhook_to_silver
-- =====================================================================

DROP TRIGGER IF EXISTS transform_webhook_to_silver ON bronze.wati_messages;

CREATE TRIGGER transform_webhook_to_silver
AFTER INSERT ON bronze.wati_messages
FOR EACH ROW
WHEN (NEW.batch_id IS NULL)  -- Only webhooks, not batch imports
EXECUTE FUNCTION bronze.transform_webhook_to_silver();

-- =====================================================================
-- BATCH PROCESSING FUNCTION FOR MESSAGES ONLY (Bronze → Silver)
-- =====================================================================

CREATE OR REPLACE FUNCTION bronze.process_messages_to_silver(p_batch_id UUID)
RETURNS JSONB AS $$
DECLARE
  v_tenant_id BIGINT;
  v_messages_created INTEGER := 0;
  v_messages_skipped INTEGER := 0;
BEGIN
  -- Get tenant_id from batch
  SELECT DISTINCT tenant_id INTO v_tenant_id
  FROM bronze.wati_messages
  WHERE batch_id = p_batch_id
  LIMIT 1;

  IF v_tenant_id IS NULL THEN
    RAISE EXCEPTION 'No messages found for batch %', p_batch_id;
  END IF;

  RAISE NOTICE 'Processing messages for batch % (tenant %)', p_batch_id, v_tenant_id;

  -- Process all messages in batch
  -- Note: Contacts must already exist in silver.contacts (process contacts first!)
  INSERT INTO silver.messages (
    tenant_id, batch_id, contact_id, wati_message_id, conversation_id, text, direction, message_type, timestamp
  )
  SELECT
    bm.tenant_id,
    p_batch_id,
    c.contact_id,
    COALESCE(bm.raw_data->>'id', bm.raw_data->>'messageId'),
    bm.raw_data->>'conversationId',
    COALESCE(bm.raw_data->>'text', bm.raw_data->>'finalText', bm.raw_data->>'eventDescription'),
    bronze.infer_message_direction(bm.raw_data, bm.wati_contact_id),
    COALESCE(bm.raw_data->>'type', 'text'),
    COALESCE(
      (bm.raw_data->>'created')::TIMESTAMPTZ,
      bm.synced_at
    )
  FROM bronze.wati_messages bm
  JOIN silver.contact_wati_keys cwk ON cwk.tenant_id = bm.tenant_id
    AND cwk.wati_contact_id = bm.wati_contact_id
  JOIN silver.contacts c ON c.tenant_id = bm.tenant_id
    AND c.contact_id = cwk.contact_id
  WHERE bm.batch_id = p_batch_id
  ON CONFLICT (tenant_id, wati_message_id) DO NOTHING;

  GET DIAGNOSTICS v_messages_created = ROW_COUNT;

  -- Count how many messages were in the batch total
  SELECT COUNT(*) INTO v_messages_skipped
  FROM bronze.wati_messages
  WHERE batch_id = p_batch_id;

  v_messages_skipped := v_messages_skipped - v_messages_created;

  RAISE NOTICE 'Complete: % messages inserted, % skipped (duplicates or no matching contact)',
    v_messages_created, v_messages_skipped;

  RETURN jsonb_build_object(
    'batch_id', p_batch_id,
    'tenant_id', v_tenant_id,
    'messages_created', v_messages_created,
    'messages_skipped', v_messages_skipped
  );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION bronze.process_messages_to_silver IS 'Process messages from bronze.wati_messages to silver.messages by joining through silver.contact_wati_keys so multiple Wati IDs can map to one canonical contact.';

-- =====================================================================
-- PROCESS CONTACTS ONLY (Bronze → Silver)
-- =====================================================================

CREATE OR REPLACE FUNCTION bronze.process_contacts_to_silver(p_batch_id UUID)
RETURNS JSONB AS $$
DECLARE
  v_tenant_id BIGINT;
  v_contacts_processed INTEGER := 0;
  v_contacts_created INTEGER := 0;
  v_contacts_updated INTEGER := 0;
BEGIN
  -- Get tenant_id from batch
  SELECT DISTINCT tenant_id INTO v_tenant_id
  FROM bronze.wati_contacts
  WHERE batch_id = p_batch_id
  LIMIT 1;

  IF v_tenant_id IS NULL THEN
    RAISE EXCEPTION 'No contacts found for batch_id: %', p_batch_id;
  END IF;

  RAISE NOTICE 'Processing batch % for tenant %', p_batch_id, v_tenant_id;

  -- Process contacts from bronze to silver
  -- Use DISTINCT ON to handle duplicates by normalized phone (take latest synced_at)
  SELECT COUNT(*) INTO v_contacts_processed
  FROM (
    SELECT DISTINCT ON (tenant_id, bronze.normalize_phone(raw_data->>'phone'))
      tenant_id
    FROM bronze.wati_contacts
    WHERE batch_id = p_batch_id
    ORDER BY tenant_id, bronze.normalize_phone(raw_data->>'phone'), synced_at DESC
  ) contacts_to_process;

  WITH contacts_to_process AS (
    SELECT DISTINCT ON (tenant_id, bronze.normalize_phone(raw_data->>'phone'))
      tenant_id,
      wati_contact_id,
      raw_data
    FROM bronze.wati_contacts
    WHERE batch_id = p_batch_id
    ORDER BY tenant_id, bronze.normalize_phone(raw_data->>'phone'), synced_at DESC
  )
  INSERT INTO silver.contacts (
    tenant_id,
    batch_id,
    phone_normalized,
    phone_raw,
    phone_raw_primary,
    name,
    wati_contact_id,
    wati_lookup_phone,
    source,
    created_at
  )
  SELECT
    tenant_id,
    p_batch_id,
    bronze.normalize_phone(raw_data->>'phone') as phone_normalized,
    raw_data->>'phone' as phone_raw,
    raw_data->>'phone' as phone_raw_primary,
    COALESCE(raw_data->>'fullName', raw_data->>'firstName') as name,
    wati_contact_id,
    bronze.normalize_phone(raw_data->>'phone') as wati_lookup_phone,
    -- Extract source by the 'source_url' custom param name (not by
    -- array position — Wati's customParams array is unordered and
    -- variable-length, so raw_data->'customParams'->3->>'value' happens
    -- to hit source_url by coincidence for some contacts and a random
    -- other field for others. Discovered during pre-backfill review.
    (
      SELECT elem->>'value'
      FROM jsonb_array_elements(COALESCE(raw_data->'customParams', '[]'::jsonb)) elem
      WHERE elem->>'name' = 'source_url'
      LIMIT 1
    ) as source,
    -- Extract created from Wati API, fallback to NOW() if not present
    COALESCE(
      (raw_data->>'created')::TIMESTAMPTZ,
      (raw_data->>'createdDateTime')::TIMESTAMPTZ,
      NOW()
    ) AS created_at
  FROM contacts_to_process
  ON CONFLICT (tenant_id, phone_normalized)
  DO UPDATE SET
    -- Merge strategy: prefer longer/non-null values
    name = CASE
      WHEN EXCLUDED.name IS NOT NULL AND
           (silver.contacts.name IS NULL OR LENGTH(EXCLUDED.name) > LENGTH(silver.contacts.name))
      THEN EXCLUDED.name
      ELSE silver.contacts.name
    END,
    source = COALESCE(EXCLUDED.source, silver.contacts.source),
    phone_raw = COALESCE(EXCLUDED.phone_raw, silver.contacts.phone_raw),
    phone_raw_primary = COALESCE(EXCLUDED.phone_raw_primary, silver.contacts.phone_raw_primary),
    wati_contact_id = COALESCE(EXCLUDED.wati_contact_id, silver.contacts.wati_contact_id),
    wati_lookup_phone = COALESCE(EXCLUDED.wati_lookup_phone, silver.contacts.wati_lookup_phone),
    updated_at = NOW();

  -- Map every Wati contact ID in the batch to the canonical silver contact.
  INSERT INTO silver.contact_wati_keys (
    tenant_id,
    contact_id,
    wati_contact_id,
    wati_lookup_phone,
    is_primary,
    last_seen_at
  )
  SELECT
    bc.tenant_id,
    sc.contact_id,
    bc.wati_contact_id,
    bronze.normalize_phone(bc.raw_data->>'phone') AS wati_lookup_phone,
    bc.wati_contact_id = sc.wati_contact_id AS is_primary,
    NOW()
  FROM bronze.wati_contacts bc
  JOIN silver.contacts sc ON sc.tenant_id = bc.tenant_id
    AND sc.phone_normalized = bronze.normalize_phone(bc.raw_data->>'phone')
  WHERE bc.batch_id = p_batch_id
    AND bc.wati_contact_id IS NOT NULL
  ON CONFLICT (tenant_id, wati_contact_id)
  DO UPDATE SET
    contact_id = EXCLUDED.contact_id,
    wati_lookup_phone = COALESCE(EXCLUDED.wati_lookup_phone, silver.contact_wati_keys.wati_lookup_phone),
    is_primary = EXCLUDED.is_primary,
    last_seen_at = NOW();

  -- Count created vs updated (approximation: check how many contacts exist)
  SELECT COUNT(*) INTO v_contacts_created
  FROM silver.contacts
  WHERE tenant_id = v_tenant_id
    AND created_at >= NOW() - INTERVAL '1 minute';

  v_contacts_updated := v_contacts_processed - v_contacts_created;

  RAISE NOTICE 'Complete: % contacts (% created, % updated)',
    v_contacts_processed, v_contacts_created, v_contacts_updated;

  -- Return summary
  RETURN jsonb_build_object(
    'batch_id', p_batch_id,
    'tenant_id', v_tenant_id,
    'contacts_processed', v_contacts_processed,
    'contacts_created', v_contacts_created,
    'contacts_updated', v_contacts_updated
  );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION bronze.process_contacts_to_silver IS 'Process contacts from bronze.wati_contacts to silver.contacts and populate silver.contact_wati_keys for all raw Wati identities in the batch.';

-- =====================================================================
-- CLASSIFIER CONFIG ACTIVATION
-- =====================================================================
-- Atomically deactivates the current active config and activates the
-- specified config in a single transaction. Prevents the race condition
-- of two sequential PostgREST calls leaving two active configs.

CREATE OR REPLACE FUNCTION public.activate_classifier_config(p_tenant_id BIGINT, p_config_id UUID)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  UPDATE public.tenant_classifier_configs
    SET is_active = false, activated_at = NULL
    WHERE tenant_id = p_tenant_id AND is_active = true;
  UPDATE public.tenant_classifier_configs
    SET is_active = true, activated_at = NOW()
    WHERE config_id = p_config_id AND tenant_id = p_tenant_id;
END;
$$;

COMMENT ON FUNCTION public.activate_classifier_config IS 'Atomically swap active classifier config for a tenant. Wraps deactivate+activate in one transaction.';

-- =====================================================================
-- USAGE EXAMPLES
-- =====================================================================

-- Merge contacts manually:
-- SELECT silver.merge_contacts(
--   p_tenant_id := 123,
--   p_source_contact_id := 'duplicate-uuid',
--   p_target_contact_id := 'canonical-uuid'
-- );

-- Process batch import contacts to silver:
-- SELECT bronze.process_contacts_to_silver('batch-uuid-here');

-- Process batch import messages to silver (messages only, contacts must exist):
-- SELECT bronze.process_messages_to_silver('batch-uuid-here');
