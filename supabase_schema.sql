-- ============================================================================
-- Growhaz WhatsApp Business AI SaaS & Live DNA Knowledge Graph Schema
-- Run once in Supabase Dashboard -> SQL Editor (Project: orhhmysimejphmtrqhlg)
-- ============================================================================

-- 1. Multi-Tenant Workspaces & Billing Settings
CREATE TABLE IF NOT EXISTS public.wa_tenants (
    tenant_id TEXT PRIMARY KEY,
    email TEXT NOT NULL DEFAULT '',
    full_name TEXT NOT NULL DEFAULT '',
    business_name TEXT NOT NULL DEFAULT '',
    custom_system_prompt TEXT NOT NULL DEFAULT '',
    billing_mode TEXT NOT NULL DEFAULT 'managed_meta',
    plan_tier TEXT NOT NULL DEFAULT 'payg',
    plan_quota INTEGER NOT NULL DEFAULT 0,
    plan_used INTEGER NOT NULL DEFAULT 0,
    plan_expires_at TEXT NOT NULL DEFAULT '',
    demo_used INTEGER NOT NULL DEFAULT 0,
    whatsapp_token TEXT NOT NULL DEFAULT '',
    whatsapp_phone_number_id TEXT NOT NULL DEFAULT '',
    whatsapp_verify_token TEXT NOT NULL DEFAULT '',
    deepseek_api_key TEXT NOT NULL DEFAULT '',
    deepseek_model TEXT NOT NULL DEFAULT 'deepseek-chat',
    groq_api_key TEXT NOT NULL DEFAULT '',
    groq_model TEXT NOT NULL DEFAULT 'llama-3.3-70b-versatile',
    openrouter_api_key TEXT NOT NULL DEFAULT '',
    openrouter_guard_model TEXT NOT NULL DEFAULT 'meta-llama/llama-guard-4-12b',
    updated_at TEXT NOT NULL DEFAULT ''
);

-- 2. Persistent WhatsApp Messages (survives Render deploys & container restarts)
CREATE TABLE IF NOT EXISTS public.wa_messages (
    msg_key TEXT PRIMARY KEY,
    id BIGINT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    phone_number TEXT NOT NULL,
    sender_name TEXT NOT NULL DEFAULT 'User',
    message TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'inbound',
    channel TEXT NOT NULL DEFAULT 'meta_whatsapp',
    status TEXT NOT NULL DEFAULT 'received',
    raw_payload TEXT NOT NULL DEFAULT '',
    ai_model TEXT DEFAULT '',
    latency_ms DOUBLE PRECISION DEFAULT 0,
    media_type TEXT DEFAULT '',
    media_url TEXT DEFAULT '',
    media_filename TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wa_messages_tenant_id ON public.wa_messages (tenant_id, id);
CREATE INDEX IF NOT EXISTS idx_wa_messages_tenant_phone ON public.wa_messages (tenant_id, phone_number);

-- 3. Customer Business Ecosystem Profiles
CREATE TABLE IF NOT EXISTS public.wa_customer_profiles (
    profile_key TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    phone_number TEXT NOT NULL,
    contact_name TEXT NOT NULL DEFAULT '',
    business_name TEXT NOT NULL DEFAULT '',
    business_category TEXT NOT NULL DEFAULT '',
    area TEXT NOT NULL DEFAULT '',
    has_website TEXT NOT NULL DEFAULT '',
    website_url TEXT NOT NULL DEFAULT '',
    existing_ecosystem TEXT NOT NULL DEFAULT '',
    pain_points TEXT NOT NULL DEFAULT '',
    goals TEXT NOT NULL DEFAULT '',
    data_source TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wa_profiles_tenant ON public.wa_customer_profiles (tenant_id, phone_number);

-- 4. Reusable Broadcast & Support Templates
CREATE TABLE IF NOT EXISTS public.wa_templates (
    tpl_key TEXT PRIMARY KEY,
    id BIGINT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    title TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'General',
    content TEXT NOT NULL DEFAULT '',
    shortcut TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

-- 5. CRM Leads Pipeline
CREATE TABLE IF NOT EXISTS public.wa_leads (
    lead_key TEXT PRIMARY KEY,
    id BIGINT NOT NULL DEFAULT 0,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    phone_number TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT 'Lead',
    source TEXT NOT NULL DEFAULT 'Manual Import',
    status TEXT NOT NULL DEFAULT 'New',
    notes TEXT NOT NULL DEFAULT '',
    last_messaged_at TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wa_leads_tenant ON public.wa_leads (tenant_id, id);

-- 6. Bookings & Follow-ups
CREATE TABLE IF NOT EXISTS public.wa_bookings (
    booking_key TEXT PRIMARY KEY,
    id BIGINT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    phone_number TEXT NOT NULL DEFAULT '',
    customer_name TEXT NOT NULL DEFAULT 'Customer',
    service_requested TEXT NOT NULL DEFAULT '',
    booking_date_time TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

-- 7. Per-Contact AI Auto-Reply Toggles
CREATE TABLE IF NOT EXISTS public.wa_contact_settings (
    setting_key TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    phone_number TEXT NOT NULL,
    bot_enabled INTEGER NOT NULL DEFAULT 1
);

-- 8. 24-Hour Conversation Billing Windows (1 Coin = INR 1)
CREATE TABLE IF NOT EXISTS public.wa_billing_windows (
    window_key TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    phone_number TEXT NOT NULL,
    billing_mode TEXT NOT NULL DEFAULT 'managed_meta',
    cost_coins DOUBLE PRECISION NOT NULL DEFAULT 0,
    charge_source TEXT NOT NULL DEFAULT 'free_demo',
    opened_at TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL DEFAULT ''
);

-- 9. OpenRouter Prompt-Injection Security Audit Log
CREATE TABLE IF NOT EXISTS public.wa_security_events (
    event_key TEXT PRIMARY KEY,
    id BIGINT NOT NULL DEFAULT 0,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    phone_number TEXT NOT NULL DEFAULT '',
    input_text TEXT NOT NULL DEFAULT '',
    detector TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    blocked INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wa_security_tenant ON public.wa_security_events (tenant_id, id DESC);

-- 10. DNA Knowledge Graph: Entity Nodes
CREATE TABLE IF NOT EXISTS public.wa_graph_nodes (
    node_key TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    label TEXT NOT NULL,
    name TEXT NOT NULL,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wa_graph_nodes_tenant_label ON public.wa_graph_nodes (tenant_id, label);

-- 11. DNA Knowledge Graph: Entity Relationships
CREATE TABLE IF NOT EXISTS public.wa_graph_edges (
    edge_key TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    source_key TEXT NOT NULL,
    source_name TEXT NOT NULL,
    relation TEXT NOT NULL,
    target_key TEXT NOT NULL,
    target_name TEXT NOT NULL,
    target_label TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wa_graph_edges_tenant_source ON public.wa_graph_edges (tenant_id, source_key);
CREATE INDEX IF NOT EXISTS idx_wa_graph_edges_tenant_relation ON public.wa_graph_edges (tenant_id, relation);

-- 12. DNA Knowledge Graph: Temporal Episodic Memory
CREATE TABLE IF NOT EXISTS public.wa_graph_episodes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    phone TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wa_graph_episodes_lookup ON public.wa_graph_episodes (tenant_id, phone, timestamp DESC);

-- Lock down all tables via RLS (only backend service/secret key bypasses RLS)
ALTER TABLE public.wa_tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_customer_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_contact_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_billing_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_security_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_graph_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_graph_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_graph_episodes ENABLE ROW LEVEL SECURITY;
