export type ResolvedTrait = {
  key: string;
  value: string;
  confidence: string;
  source: string;
  reason: string;
};

export type ConversationLine = {
  id: string;
  speaker: "Customer" | "Business";
  text: string;
};

export type ContactInspectorRecord = {
  contactId: string;
  name: string;
  lastActivity: string;
  lastInbound: string;
  journeyKey: string;
  journeyLabel: string;
  routingRule: string;
  routingConfigVersion: string;
  routingReason: string;
  stageKey: string;
  stageLabel: string;
  stageState: "current" | "stale" | "missing";
  confidence: string;
  classifiedAt: string;
  traits: ResolvedTrait[];
  conversation: ConversationLine[];
};

export const contactInspectorRecords: ContactInspectorRecord[] = [
  {
    contactId: "contact-alma",
    name: "Alma",
    lastActivity: "Today 09:11",
    lastInbound: "Today 09:10",
    journeyKey: "wholesale_buyers",
    journeyLabel: "Wholesale Buyers",
    routingRule: "Rule #1 · customer_type = wholesale",
    routingConfigVersion: "v4",
    routingReason: "Trait Classifier resolved `customer_type = wholesale` after the customer asked for pricing on 50 units.",
    stageKey: "wholesale_quoted",
    stageLabel: "Quoted",
    stageState: "current",
    confidence: "0.86",
    classifiedAt: "Today 09:11",
    traits: [
      {
        key: "customer_type",
        value: "wholesale",
        confidence: "0.86",
        source: "Trait Classifier · Customer Type Classifier v1",
        reason: "The chat asks for bulk pricing and mentions starting with 50 units.",
      },
      {
        key: "preferred_language",
        value: "es",
        confidence: "1.00",
        source: "Imported rule",
        reason: "Conversation language detected as Spanish from the latest messages.",
      },
    ],
    conversation: [
      { id: "alma-1", speaker: "Customer", text: "Hi, do you have wholesale pricing if we start with 50 units?" },
      { id: "alma-2", speaker: "Business", text: "Yes. We can share tiers. What volume are you expecting monthly?" },
      { id: "alma-3", speaker: "Customer", text: "Around 50 now and more later if it works." },
    ],
  },
  {
    contactId: "contact-jose",
    name: "Jose",
    lastActivity: "Today 08:58",
    lastInbound: "Today 08:56",
    journeyKey: "wholesale_buyers",
    journeyLabel: "Wholesale Buyers",
    routingRule: "Rule #1 · customer_type = wholesale",
    routingConfigVersion: "v4",
    routingReason: "The contact stayed in the wholesale journey after the trait classifier kept `customer_type = wholesale`, but the latest exchange no longer shows active buying intent.",
    stageKey: "wholesale_lost",
    stageLabel: "Lost",
    stageState: "current",
    confidence: "0.79",
    classifiedAt: "Today 08:58",
    traits: [
      {
        key: "customer_type",
        value: "wholesale",
        confidence: "0.88",
        source: "Trait Classifier · Customer Type Classifier v1",
        reason: "The thread is about quoted bulk pricing and follow-up on a prior wholesale offer.",
      },
      {
        key: "is_existing_customer",
        value: "false",
        confidence: "1.00",
        source: "Imported attribute",
        reason: "CRM export shows this lead has not converted before.",
      },
    ],
    conversation: [
      { id: "jose-1", speaker: "Business", text: "We shared the wholesale quote yesterday. Do you want to move forward?" },
      { id: "jose-2", speaker: "Customer", text: "Not right now. We are pausing this project for the moment." },
    ],
  },
  {
    contactId: "contact-paula",
    name: "Paula",
    lastActivity: "Today 09:03",
    lastInbound: "Today 09:02",
    journeyKey: "wholesale_buyers",
    journeyLabel: "Wholesale Buyers",
    routingRule: "Rule #1 · customer_type = wholesale",
    routingConfigVersion: "v4",
    routingReason: "The route stayed in wholesale because the contact is negotiating pricing and volume for a business order.",
    stageKey: "wholesale_negotiating",
    stageLabel: "Negotiating",
    stageState: "current",
    confidence: "0.82",
    classifiedAt: "Today 09:03",
    traits: [
      {
        key: "customer_type",
        value: "wholesale",
        confidence: "0.91",
        source: "Trait Classifier · Customer Type Classifier v1",
        reason: "The customer is discussing tiers, quantities, and a counter-offer for business pricing.",
      },
      {
        key: "preferred_language",
        value: "es",
        confidence: "1.00",
        source: "Imported rule",
        reason: "The underlying contact record is already tagged as Spanish-speaking.",
      },
    ],
    conversation: [
      { id: "paula-1", speaker: "Customer", text: "If we increase the quantity, can you improve the price per unit?" },
      { id: "paula-2", speaker: "Business", text: "Yes, we can move to the next tier if you confirm the larger order." },
      { id: "paula-3", speaker: "Customer", text: "Send me the revised tier and I will review it with the team." },
    ],
  },
  {
    contactId: "contact-carlos",
    name: "Carlos",
    lastActivity: "Today 08:44",
    lastInbound: "Today 08:40",
    journeyKey: "vip_recovery",
    journeyLabel: "VIP Recovery",
    routingRule: "Rule #2 · trait.label = vip",
    routingConfigVersion: "v4",
    routingReason: "Imported VIP label outranked the fallback routing path and placed the contact into the recovery journey.",
    stageKey: "vip_warm",
    stageLabel: "Warm",
    stageState: "stale",
    confidence: "0.73",
    classifiedAt: "Yesterday 17:02",
    traits: [
      {
        key: "is_existing_customer",
        value: "true",
        confidence: "1.00",
        source: "Imported attribute",
        reason: "Historical CRM export marks this contact as a previous customer.",
      },
      {
        key: "vip_label",
        value: "vip",
        confidence: "1.00",
        source: "Imported attribute",
        reason: "VIP segment was provided in the source data.",
      },
    ],
    conversation: [
      { id: "carlos-1", speaker: "Business", text: "We have a reactivation offer if you want to come back this week." },
      { id: "carlos-2", speaker: "Customer", text: "Maybe. What would the new package look like?" },
      { id: "carlos-3", speaker: "Business", text: "I can share the new option and pricing if helpful." },
    ],
  },
  {
    contactId: "contact-julia",
    name: "Julia",
    lastActivity: "Yesterday 18:20",
    lastInbound: "Yesterday 18:18",
    journeyKey: "retail_buyers",
    journeyLabel: "Retail Buyers",
    routingRule: "Rule #3 · preferred_language = es",
    routingConfigVersion: "v4",
    routingReason: "Routing placed this contact in the LATAM retail path after the preferred language rule matched.",
    stageKey: "retail_ready",
    stageLabel: "Ready to Buy",
    stageState: "missing",
    confidence: "—",
    classifiedAt: "—",
    traits: [
      {
        key: "preferred_language",
        value: "es",
        confidence: "1.00",
        source: "Imported rule",
        reason: "Source dataset already provides Spanish as the preferred language.",
      },
    ],
    conversation: [
      { id: "julia-1", speaker: "Customer", text: "Hola, cuánto tarda la entrega si compro hoy?" },
      { id: "julia-2", speaker: "Business", text: "Podemos entregar esta semana. También te comparto el precio final." },
    ],
  },  {
    contactId: "contact-mateo",
    name: "Mateo",
    lastActivity: "Yesterday 18:02",
    lastInbound: "Yesterday 18:00",
    journeyKey: "retail_buyers",
    journeyLabel: "Retail Buyers",
    routingRule: "Rule #4 · else",
    routingConfigVersion: "v4",
    routingReason: "No special trait rules matched, so this chat stayed in the default retail buyers journey.",
    stageKey: "retail_browsing",
    stageLabel: "Browsing",
    stageState: "current",
    confidence: "0.77",
    classifiedAt: "Yesterday 18:02",
    traits: [
      {
        key: "preferred_language",
        value: "en",
        confidence: "1.00",
        source: "Imported rule",
        reason: "The imported contact data marks English as the preferred language.",
      },
    ],
    conversation: [
      { id: "mateo-1", speaker: "Customer", text: "I am just looking around for now. What colors do you have?" },
      { id: "mateo-2", speaker: "Business", text: "We have three colors available and can share photos if you want." },
    ],
  },
];

export function getContactInspectorRecord(contactId: string) {
  return contactInspectorRecords.find((record) => record.contactId === contactId);
}
