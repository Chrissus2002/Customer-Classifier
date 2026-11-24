export type JourneySummary = {
  journeyKey: string;
  name: string;
  activeVersion: string;
  draftStatus: string;
  enrolled: string;
  staleCount: string;
  lastUpdated: string;
  lastEval: string;
  note: string;
  sampleContactId: string;
};

export type JourneyChange = {
  time: string;
  item: string;
  detail: string;
};

export const journeySummaries: JourneySummary[] = [
  {
    journeyKey: "retail_buyers",
    name: "Retail Buyers",
    activeVersion: "v3",
    draftStatus: "yes",
    enrolled: "6,214",
    staleCount: "124",
    lastUpdated: "09:12 UTC",
    lastEval: "88%",
    note: "General B2C purchase journey for the default segment.",
    sampleContactId: "contact-julia",
  },
  {
    journeyKey: "wholesale_buyers",
    name: "Wholesale Buyers",
    activeVersion: "v2",
    draftStatus: "yes",
    enrolled: "412",
    staleCount: "19",
    lastUpdated: "08:05 UTC",
    lastEval: "91%",
    note: "B2B flow with quoted, negotiating, won, and lost states.",
    sampleContactId: "contact-alma",
  },
  {
    journeyKey: "vip_recovery",
    name: "VIP Recovery",
    activeVersion: "v1",
    draftStatus: "no",
    enrolled: "88",
    staleCount: "7",
    lastUpdated: "Yesterday",
    lastEval: "—",
    note: "Retention and reactivation track for labeled high-value contacts.",
    sampleContactId: "contact-carlos",
  },
];

export const recentJourneyChanges: JourneyChange[] = [
  { time: "09:12", item: "retail_buyers draft updated", detail: "Prompt tightened around late-stage purchase intent." },
  { time: "08:41", item: "routing rules changed", detail: "customer_type now routes wholesale contacts earlier." },
  { time: "08:05", item: "wholesale_buyers v2 activated", detail: "Negotiation stage split from quoted." },
];

export function getJourneySummary(journeyKey: string) {
  return journeySummaries.find((journey) => journey.journeyKey === journeyKey);
}
