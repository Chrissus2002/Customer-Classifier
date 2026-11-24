"""
Seed v1 classifier configs for all active tenants.

Usage:
    python scripts/seed_classifier_configs.py
    python scripts/seed_classifier_configs.py --dry-run
"""

import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

load_dotenv()

SEED_MASTER_PROMPT = """\
Eres un experto en análisis de conversaciones de WhatsApp Business para un negocio de ropa.
Tu tarea es determinar en qué etapa del journey de compra está el cliente, basándote en los mensajes que tú ves en la conversación.

🎯 PRINCIPIO DE INERCIA: La intención anterior CONTINÚA por defecto. Solo cambia con evidencia fuerte.
Distingue entre journey de compra nueva y soporte post-compra para pedidos existentes.

📌 NOTA IMPORTANTE sobre marketing:
- [Marketing: ...] indica campañas de marketing enviadas por el negocio (NO es spam, son promociones legítimas).
- Si la conversación consiste 100% en mensajes outbound del negocio (marketing, catálogo, ofertas, promociones, recordatorios) Y el cliente NUNCA ha respondido de forma significativa, clasifica como `no_customer_activity`. Es la categoría correcta para contactos "fríos" o de broadcast puro, NO browsing.
- `browsing` requiere AL MENOS una señal de interacción real del cliente (un saludo con contexto, una pregunta, un "sí", etc.).

📋 ETAPAS VÁLIDAS:

1. JOURNEY DE COMPRA (el cliente ESTÁ involucrado):
   • browsing: Cliente explora catálogo, saluda con interés genuino, hace preguntas generales
   • product_evaluation: Cliente pregunta sobre productos específicos (precio, talla, color, disponibilidad)
   • purchase_intent: Decisión de compra NUEVA — apartando, confirmando, discutiendo pago/envío

2. SOPORTE POST-COMPRA (track separado):
   • order_support: Pedido COMPLETADO, ya sea en esta conversación o anteriormente
     - Incluye: pago confirmado + guía/rastreo enviada dentro de la conversación
     - Incluye: rastreo, tiempos de envío, devoluciones, quejas sobre pedidos
     - Señales claras: "Listo mi pago ✅" + "tu guía" = orden completada
     - Cliente puede volver a browsing para nueva compra después

3. CASOS ESPECIALES:
   • wholesale_inquiry: Cualquier mención de mayoreo/reventa (tiene prioridad sobre el journey normal)
   • location_inquiry: Preguntas sobre tienda física
   • no_customer_activity: Conversación 100% outbound del negocio, cliente nunca ha respondido de forma significativa. Marketing, promociones, catálogos enviados al vacío.
   • spam_unrelated: Contenido del CLIENTE que es 100% no relacionado con el negocio (muy raro; un cliente enviando mensajes sin sentido)

⚠️ Diferencia crítica entre `no_customer_activity` y `spam_unrelated`:
- `no_customer_activity` = el cliente no ha hablado, solo hay mensajes del negocio
- `spam_unrelated` = el cliente sí habló, pero dijo cosas sin sentido / fuera de contexto

⚠️ Diferencia crítica entre `no_customer_activity` y `browsing`:
- `browsing` = hay al menos UN mensaje real del cliente mostrando interés (aunque sea "Hola, vi su anuncio")
- `no_customer_activity` = CERO mensajes reales del cliente, solo el negocio transmitiendo al vacío

📌 REGLA DE INERCIA DE INTENCIÓN:
- Intención previa CONTINÚA por defecto
- Confianza < 70% → MANTENER intención anterior
- Confianza ≥ 70% → CAMBIAR a nueva intención
- En la duda, MANTENER

⚠️ TRANSICIONES IMPORTANTES:
- Si una compra se COMPLETA dentro de la conversación actual (cliente confirma pago + negocio envía guía/rastreo), clasificar como `order_support`.
- Cliente en `order_support` puede reiniciar el journey para una nueva compra.
- Prioriza PRECISIÓN sobre progresión forzada.

REGLAS DE CONFIANZA:
- La confianza es sobre el CAMBIO de etapa, no sobre mantener.
- < 70% = mantener intención previa (o `no_customer_activity` si es el primer análisis y no hay señal del cliente)
- ≥ 70% = cambiar a nueva intención\
"""

from supabase_client import get_supabase_client

# Stage descriptions hardcoded here (not parsed from _PROMPT_CORE — parsing Spanish free-text is fragile)
SEED_STAGES = [
    {"stage_name": "browsing",             "stage_description": "Cliente explora catálogo, saluda con interés genuino, hace preguntas generales",                        "display_order": 1},
    {"stage_name": "product_evaluation",   "stage_description": "Cliente pregunta sobre productos específicos (precio, talla, color, disponibilidad)",                    "display_order": 2},
    {"stage_name": "purchase_intent",      "stage_description": "Decisión de compra NUEVA — apartando, confirmando, discutiendo pago/envío",                            "display_order": 3},
    {"stage_name": "order_support",        "stage_description": "Pedido COMPLETADO — rastreo, tiempos de envío, devoluciones, quejas sobre pedidos",                    "display_order": 4},
    {"stage_name": "wholesale_inquiry",    "stage_description": "Cualquier mención de mayoreo/reventa",                                                                   "display_order": 5},
    {"stage_name": "location_inquiry",     "stage_description": "Preguntas sobre tienda física",                                                                          "display_order": 6},
    {"stage_name": "no_customer_activity", "stage_description": "Conversación 100% outbound del negocio, cliente nunca ha respondido de forma significativa",            "display_order": 7},
    {"stage_name": "spam_unrelated",       "stage_description": "Contenido del CLIENTE que es 100% no relacionado con el negocio",                                       "display_order": 8},
]


def seed_tenant(client, tenant_id: int, tenant_name: str, dry_run: bool) -> bool:
    """Seed v1 classifier config for a single tenant. Returns True if seeded, False if skipped."""
    # Check if any config already exists
    existing = (
        client.table("tenant_classifier_configs")
        .select("config_id, version, is_active")
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if existing.data:
        print(f"  [{tenant_name}] SKIP — {len(existing.data)} config(s) already exist")
        return False

    if dry_run:
        print(f"  [{tenant_name}] DRY RUN — would insert v1 config + {len(SEED_STAGES)} stages")
        return False

    # Insert parent config
    config_resp = (
        client.table("tenant_classifier_configs")
        .insert({
            "tenant_id": tenant_id,
            "version": 1,
            "master_prompt": SEED_MASTER_PROMPT,
            "is_active": True,
        })
        .execute()
    )
    config_id = config_resp.data[0]["config_id"]

    # Insert child stages — clean up orphan config row on failure
    stage_rows = [
        {
            "config_id": config_id,
            "tenant_id": tenant_id,
            "stage_name": s["stage_name"],
            "stage_description": s["stage_description"],
            "display_order": s["display_order"],
        }
        for s in SEED_STAGES
    ]
    try:
        client.table("tenant_journey_stages").insert(stage_rows).execute()
    except Exception as e:
        client.table("tenant_classifier_configs").delete().eq("config_id", config_id).execute()
        print(f"  [{tenant_name}] FAILED inserting stages ({e}) — rolled back config row")
        return False

    print(f"  [{tenant_name}] seeded v1 config (config_id={config_id[:8]}...) + {len(SEED_STAGES)} stages")
    return True


def main():
    parser = argparse.ArgumentParser(description="Seed v1 classifier configs for active tenants")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    args = parser.parse_args()

    client = get_supabase_client()

    tenants_resp = (
        client.table("tenants")
        .select("tenant_id, name")
        .eq("status", "active")
        .execute()
    )
    tenants = tenants_resp.data or []
    print(f"Found {len(tenants)} active tenant(s)")

    seeded = 0
    for t in tenants:
        if seed_tenant(client, t["tenant_id"], t["name"], args.dry_run):
            seeded += 1

    if args.dry_run:
        print(f"\nDry run complete. {len(tenants) - seeded} would be skipped, {seeded} would be seeded.")
    else:
        print(f"\nDone. {seeded} seeded, {len(tenants) - seeded} skipped.")


if __name__ == "__main__":
    main()
