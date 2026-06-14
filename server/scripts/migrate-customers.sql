-- Metalins schema migration — Customer auth layer (D-PROD.13).
--
-- Ejecutar en Supabase SQL Editor o via `psql $METALINS_DB_URL`.
-- ANTES de cualquier deploy que mande el modelo Customer + APIKey.customer_id
-- a prod (Sprint 3a.0 lo aprendió a la fuerza con un 500 en bootstrap-api-key).
--
-- Idempotente: se puede correr múltiples veces sin error.
--
-- Sobre RLS (Row Level Security): Supabase advierte al crear tabla nueva.
-- **Habilitar RLS** ("Run and enable RLS"). Razón: defense in depth.
-- Nuestro server FastAPI (Cloud Run) usa connection string directa via psycopg,
-- lo cual **bypassea RLS**. Sin policies, anon/authenticated keys de Supabase
-- (que solo se usan desde el JS client) NO pueden tocar estas tablas. Si en el
-- futuro alguien agrega Supabase JS client al frontend para queries directas,
-- va a fallar cerrado — comportamiento deseado.
--
-- NO agregamos policies en este script porque ningún cliente legítimo accede
-- via JS client. Si en Sprint 3b o más adelante decidimos exponer queries
-- directas, agregar policies entonces (e.g. `customers` row visible solo si
-- `id = auth.uid()`).

-- ----------------------------------------------------------------------------
-- 1. Tabla customers (nueva)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    id                 TEXT PRIMARY KEY,
    email              TEXT NOT NULL UNIQUE,
    plan               TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id TEXT,
    metadata_json      JSONB DEFAULT '{}'::jsonb,
    created_at         TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_customers_email ON customers (email);

-- ----------------------------------------------------------------------------
-- 2. FK api_keys.customer_id (nullable hasta Sprint 3b)
-- ----------------------------------------------------------------------------
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS customer_id TEXT REFERENCES customers(id);
CREATE INDEX IF NOT EXISTS ix_api_keys_customer_id ON api_keys (customer_id);

-- ----------------------------------------------------------------------------
-- 3. Verificación
-- ----------------------------------------------------------------------------
SELECT 'customers table exists' AS check,
       EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='customers') AS ok
UNION ALL
SELECT 'api_keys.customer_id exists',
       EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='api_keys' AND column_name='customer_id');

-- ----------------------------------------------------------------------------
-- 4. (Sprint 3b only — NO correr todavía) Asignar keys huérfanas a admin
-- ----------------------------------------------------------------------------
-- En Sprint 3b, cuando Jose haga su primer magic-link login y se cree su
-- customer row, hacer:
--
-- INSERT INTO customers (id, email, plan) VALUES (
--     '<jose-supabase-uuid>',  -- substituir con auth.users.id real
--     'founder@metalins.com',
--     'free'
-- ) ON CONFLICT (id) DO NOTHING;
--
-- UPDATE api_keys SET customer_id = '<jose-supabase-uuid>' WHERE customer_id IS NULL;
--
-- ALTER TABLE api_keys ALTER COLUMN customer_id SET NOT NULL;
