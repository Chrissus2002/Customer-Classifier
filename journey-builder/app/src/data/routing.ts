export type RoutingRuleSummary = {
  id: string;
  order: number;
  when: string;
  then: string;
  status: string;
};

export type RoutingPreviewRow = {
  contactId: string;
  contact: string;
  oldJourney: string;
  newJourney: string;
  why: string;
};

export const routingRules: RoutingRuleSummary[] = [
  { id: "rule-1", order: 1, when: "customer_type = wholesale", then: "wholesale_buyers", status: "active" },
  { id: "rule-2", order: 2, when: "trait.label = vip", then: "vip_recovery", status: "active" },
  { id: "rule-3", order: 3, when: "preferred_language = es", then: "retail_buyers_latam", status: "active" },
  { id: "rule-4", order: 4, when: "else", then: "retail_buyers", status: "fallback" },
];

export const routingPreview: RoutingPreviewRow[] = [
  {
    contactId: "contact-alma",
    contact: "Alma",
    oldJourney: "retail_buyers",
    newJourney: "wholesale_buyers",
    why: "Trait Classifier resolved customer_type = wholesale for this chat_id.",
  },
  {
    contactId: "contact-carlos",
    contact: "Carlos",
    oldJourney: "retail_buyers",
    newJourney: "vip_recovery",
    why: "Imported VIP label now outranks the fallback rule.",
  },
  {
    contactId: "contact-julia",
    contact: "Julia",
    oldJourney: "retail_buyers",
    newJourney: "retail_buyers_latam",
    why: "preferred_language = es for this contact.",
  },
];
