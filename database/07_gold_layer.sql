-- =====================================================================
-- File: database/07_gold_layer.sql
-- Purpose: Gold Layer - Analytics Views
-- Pre-computed views for dashboards and exports
-- =====================================================================

-- Create gold schema
CREATE SCHEMA IF NOT EXISTS gold;

-- =====================================================================
-- ANALYTICS VIEWS
-- =====================================================================

-- Overall metrics per tenant
CREATE OR REPLACE VIEW gold.contact_metrics AS
SELECT
  tenant_id,
  COUNT(*) as total_contacts,
  COUNT(*) FILTER (WHERE is_canonical = true) as active_contacts,
  COUNT(*) FILTER (WHERE is_canonical = false) as merged_contacts,
  MIN(created_at) as first_contact_at,
  MAX(created_at) as latest_contact_at
FROM silver.contacts
GROUP BY tenant_id;

COMMENT ON VIEW gold.contact_metrics IS 'Tenant-level summary statistics for contacts';

-- Per-contact activity summary (for dashboards)
CREATE OR REPLACE VIEW gold.contact_activity AS
SELECT
  c.tenant_id,
  c.contact_id,
  c.phone_identity_key,
  c.phone_e164,
  c.phone_normalized,
  c.wati_lookup_phone,
  COALESCE(c.phone_e164, c.phone_raw_primary, c.phone_normalized) AS display_phone,
  c.name,
  c.created_at as contact_created_at,
  COUNT(m.message_id) as message_count,
  COUNT(m.message_id) FILTER (WHERE m.direction = 'inbound') as inbound_count,
  COUNT(m.message_id) FILTER (WHERE m.direction = 'outbound') as outbound_count,
  MAX(m.timestamp) as last_message_at,
  MIN(m.timestamp) as first_message_at,
  MAX(m.timestamp) FILTER (WHERE m.direction = 'inbound') as last_inbound_at,
  -- Latest journey classification
  (
    SELECT jr.journey_stage
    FROM silver.journey_intent_results jr
    WHERE jr.contact_id = c.contact_id
    ORDER BY jr.classified_at DESC
    LIMIT 1
  ) as current_journey_stage
FROM silver.contacts c
LEFT JOIN silver.messages m ON c.contact_id = m.contact_id
WHERE c.is_canonical = true
GROUP BY
  c.tenant_id,
  c.contact_id,
  c.phone_identity_key,
  c.phone_e164,
  c.phone_normalized,
  c.wati_lookup_phone,
  COALESCE(c.phone_e164, c.phone_raw_primary, c.phone_normalized),
  c.name,
  c.created_at;

COMMENT ON VIEW gold.contact_activity IS 'Per-contact engagement data with both canonical and Wati-facing phone fields for dashboards and exports';

-- Journey stage distribution per tenant
CREATE OR REPLACE VIEW gold.journey_distribution AS
SELECT
  c.tenant_id,
  COALESCE(jr.journey_stage, 'unclassified') as journey_stage,
  COUNT(DISTINCT c.contact_id) as contact_count
FROM silver.contacts c
LEFT JOIN LATERAL (
  SELECT journey_stage
  FROM silver.journey_intent_results
  WHERE contact_id = c.contact_id
  ORDER BY classified_at DESC
  LIMIT 1
) jr ON true
WHERE c.is_canonical = true
GROUP BY c.tenant_id, jr.journey_stage;

COMMENT ON VIEW gold.journey_distribution IS 'Journey stage distribution for funnel charts - contact count per stage';

-- Engagement segments (for CSV export)
CREATE OR REPLACE VIEW gold.engaged_contacts AS
SELECT
  ca.*,
  CASE
    WHEN ca.last_message_at > NOW() - INTERVAL '30 days' THEN 'active_30d'
    WHEN ca.last_message_at > NOW() - INTERVAL '90 days' THEN 'active_90d'
    ELSE 'inactive'
  END as engagement_tier
FROM gold.contact_activity ca;

COMMENT ON VIEW gold.engaged_contacts IS 'Segmented contacts with engagement tiers - used for CSV exports and campaigns';

-- =====================================================================
-- USAGE EXAMPLES
-- =====================================================================

-- Get tenant-level metrics:
-- SELECT * FROM gold.contact_metrics WHERE tenant_id = 'tenant-uuid';

-- Get contact activity for a tenant:
-- SELECT * FROM gold.contact_activity WHERE tenant_id = 'tenant-uuid';

-- Get journey stage distribution:
-- SELECT * FROM gold.journey_distribution WHERE tenant_id = 'tenant-uuid';

-- Export engaged contacts for campaigns:
-- SELECT * FROM gold.engaged_contacts
-- WHERE tenant_id = 'tenant-uuid'
--   AND engagement_tier = 'active_30d'
--   AND current_journey_stage = 'purchase_intent';
