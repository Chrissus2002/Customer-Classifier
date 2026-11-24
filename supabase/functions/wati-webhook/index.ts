// Supabase Edge Function: wati-webhook
// Purpose: Receive Wati webhooks and log to database for trigger-based processing
// Design: Minimal - just log and return. Triggers handle all processing (stateless, resilient)

import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.38.4";

// CORS headers for webhook requests
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

serve(async (req: Request) => {
  // Handle CORS preflight requests
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  // Only accept POST
  if (req.method !== 'POST') {
    return new Response('Method not allowed', { status: 405 })
  }

  try {
    // 1. Extract tenant_id from URL path
    const url = new URL(req.url);
    const pathParts = url.pathname.split("/");
    const tenantIdStr = pathParts[pathParts.length - 1]; // Last segment is tenant ID

    if (!tenantIdStr || tenantIdStr === "wati-webhook") {
      return new Response(
        JSON.stringify({
          error: "Missing tenant ID in URL path",
          usage: "POST /wati-webhook/{tenant-id}"
        }),
        {
          status: 400,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        }
      );
    }

    // Validate numeric format and convert to bigint
    const tenantId = parseInt(tenantIdStr, 10);
    if (isNaN(tenantId) || tenantId <= 0) {
      return new Response(
        JSON.stringify({
          error: "Invalid tenant ID format. Expected positive integer.",
          received: tenantIdStr
        }),
        {
          status: 400,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        }
      );
    }

    // 2. Initialize Supabase client (service role key for admin operations)
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const supabaseServiceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const supabase = createClient(supabaseUrl, supabaseServiceKey);

    // 3. Validate tenant exists and is active
    const { data: tenant, error: tenantError } = await supabase
      .from("tenants")
      .select("tenant_id, name, status")
      .eq("tenant_id", tenantId)
      .eq("status", "active")
      .single();

    if (tenantError || !tenant) {
      console.error("Tenant validation failed:", tenantError);
      // Return 200 so Wati does not retry — a 4xx causes Wati to retry the
      // webhook repeatedly and eventually disable the endpoint entirely.
      return new Response(
        JSON.stringify({
          received: true,
          error: "Tenant not found or inactive",
          tenant_id: tenantId
        }),
        {
          status: 200,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        }
      );
    }

    console.log(`Webhook received for tenant: ${tenant.name} (${tenantId})`);

    // 4. Parse webhook payload
    const payload = await req.json();

    // 4a. Validate required field: message ID
    const messageId = payload?.id ?? payload?.messageId;
    if (!messageId) {
      return new Response(
        JSON.stringify({ error: "Invalid payload: missing message id (id or messageId)" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    // 4b. Detect direction — absence of waId means outbound (sent by business)
    const direction = payload?.waId ? "inbound" : "outbound";
    console.log(`Message direction: ${direction} for tenant ${tenantId}`);

    // 5. Log webhook to database
    // IMPORTANT: This is ALL the Edge Function does. Triggers handle everything else!
    const { error: logError } = await supabase
      .from("webhook_logs")
      .insert({
        tenant_id: tenantId,
        method: req.method,
        url: req.url,
        headers: Object.fromEntries(req.headers.entries()),
        payload: { ...payload, _direction: direction },
      });

    if (logError) {
      console.error("Failed to log webhook:", logError);
      return new Response(
        JSON.stringify({
          error: "Failed to log webhook",
          details: logError.message
        }),
        {
          status: 500,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        }
      );
    }

    console.log(`Webhook logged successfully for tenant ${tenantId}`);

    // 6. Return 200 OK immediately
    // Database triggers will process the webhook asynchronously
    return new Response(
      JSON.stringify({
        success: true,
        message: "Webhook received and logged",
        tenant_id: tenantId
      }),
      {
        status: 200,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      }
    );

  } catch (error) {
    console.error("Edge Function error:", error);
    return new Response(
      JSON.stringify({
        error: "Internal server error",
        message: error instanceof Error ? error.message : "Unknown error"
      }),
      {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      }
    );
  }
});
