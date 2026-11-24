export type StageDefinition = {
  key: string;
  label: string;
  description: string;
};

export type EvalSummaryRow = {
  contactId: string;
  contact: string;
  expected: string;
  active: string;
  draft: string;
  why: string;
};

export type VersionHistoryEntry = {
  version: string;
  status: string;
  changedAt: string;
  note: string;
};

export type JourneyStudioRecord = {
  journeyKey: string;
  journeyLabel: string;
  activeVersion: string;
  draftVersion: string;
  unsavedChanges: string;
  prompt: string;
  draftNotes: string;
  stages: StageDefinition[];
  versionHistory: VersionHistoryEntry[];
  evalMetrics: {
    agreement: string;
    agreementDelta: string;
    changedLabels: string;
    changedLabelsNote: string;
    confidenceAvg: string;
    confidenceDelta: string;
  };
  evalRows: EvalSummaryRow[];
};

export const journeyStudioRecords: JourneyStudioRecord[] = [
  {
    journeyKey: "wholesale_buyers",
    journeyLabel: "Wholesale Buyers",
    activeVersion: "v2",
    draftVersion: "v3",
    unsavedChanges: "3 staged edits",
    prompt: `You classify B2B wholesale conversations.\n\nPrefer current customer intent over early curiosity.\nIgnore operational and admin noise.\nUse only valid labels.\nDistinguish quoted from negotiating when pricing back-and-forth exists.`,
    draftNotes: "Split `quoted` from `negotiating` and tightened reseller logic.",
    stages: [
      { key: "wholesale_new", label: "New Lead", description: "Early B2B discovery with no quote yet." },
      { key: "wholesale_quoted", label: "Quoted", description: "Pricing or tiers have been provided." },
      { key: "wholesale_negotiating", label: "Negotiating", description: "Customer is responding to pricing or terms." },
      { key: "wholesale_won", label: "Won", description: "Customer confirmed the order or next transaction step." },
      { key: "wholesale_lost", label: "Lost", description: "Lead dropped, declined, or went inactive after quote." },
    ],
    versionHistory: [
      { version: "v3", status: "Draft", changedAt: "Today 09:12", note: "Added stage split between quoted and negotiating." },
      { version: "v2", status: "Active", changedAt: "Today 08:05", note: "Current production classifier for B2B leads." },
      { version: "v1", status: "Archived", changedAt: "Yesterday", note: "Original wholesale stage set." },
    ],
    evalMetrics: {
      agreement: "88%",
      agreementDelta: "+10% vs active",
      changedLabels: "14 / 50",
      changedLabelsNote: "Need inspection",
      confidenceAvg: "0.81",
      confidenceDelta: "Up from 0.74",
    },
    evalRows: [
      {
        contactId: "contact-alma",
        contact: "Alma",
        expected: "wholesale_quoted",
        active: "wholesale_new",
        draft: "wholesale_quoted",
        why: "Pricing request detected in the latest reply.",
      },
      {
        contactId: "contact-jose",
        contact: "Jose",
        expected: "wholesale_lost",
        active: "wholesale_quoted",
        draft: "wholesale_lost",
        why: "No active buying intent after quote delivery.",
      },
      {
        contactId: "contact-paula",
        contact: "Paula",
        expected: "wholesale_negotiating",
        active: "wholesale_quoted",
        draft: "wholesale_negotiating",
        why: "Counter-offer present in the follow-up exchange.",
      },
    ],
  },
  {
    journeyKey: "retail_buyers",
    journeyLabel: "Retail Buyers",
    activeVersion: "v3",
    draftVersion: "v4",
    unsavedChanges: "1 staged edit",
    prompt: `You classify B2C retail conversations.\n\nPrefer immediate buying intent over generic browsing.\nIgnore order-status or support-only exchanges.\nChoose the most current valid stage only.`,
    draftNotes: "Tightened the boundary between browsing and ready_to_buy.",
    stages: [
      { key: "retail_browsing", label: "Browsing", description: "Customer is exploring without clear buying intent yet." },
      { key: "retail_ready", label: "Ready to Buy", description: "Customer is asking about price, delivery, or payment to complete purchase." },
      { key: "retail_checkout", label: "Checkout", description: "Customer is confirming payment or order details." },
      { key: "retail_post_purchase", label: "Post Purchase", description: "Conversation is after the transaction." },
    ],
    versionHistory: [
      { version: "v4", status: "Draft", changedAt: "Today 09:12", note: "Sharper ready-to-buy guidance." },
      { version: "v3", status: "Active", changedAt: "This week", note: "Current retail buyer classifier." },
    ],
    evalMetrics: {
      agreement: "84%",
      agreementDelta: "+4% vs active",
      changedLabels: "9 / 40",
      changedLabelsNote: "Mostly browsing vs ready_to_buy",
      confidenceAvg: "0.78",
      confidenceDelta: "Up from 0.73",
    },
    evalRows: [
      {
        contactId: "contact-julia",
        contact: "Julia",
        expected: "retail_ready",
        active: "retail_browsing",
        draft: "retail_ready",
        why: "Payment and delivery questions indicate intent to buy now.",
      },
      {
        contactId: "contact-mateo",
        contact: "Mateo",
        expected: "retail_browsing",
        active: "retail_ready",
        draft: "retail_browsing",
        why: "Conversation stayed exploratory without concrete buying signals.",
      },
    ],
  },
  {
    journeyKey: "vip_recovery",
    journeyLabel: "VIP Recovery",
    activeVersion: "v1",
    draftVersion: "v2",
    unsavedChanges: "No unsaved edits",
    prompt: `You classify VIP recovery conversations.\n\nFocus on reactivation signals, positive replies, and churn risk.\nIgnore administrative follow-up that does not change account intent.`,
    draftNotes: "Draft v2 adds a clearer distinction between warm recovery and churn risk.",
    stages: [
      { key: "vip_cold", label: "Cold", description: "No meaningful re-engagement yet." },
      { key: "vip_warm", label: "Warm", description: "Customer has re-engaged and is open to follow-up." },
      { key: "vip_saved", label: "Saved", description: "Customer clearly accepts recovery offer or next step." },
      { key: "vip_at_risk", label: "At Risk", description: "Conversation signals likely churn or disengagement." },
    ],
    versionHistory: [
      { version: "v2", status: "Draft", changedAt: "Today 07:58", note: "Added warm vs at-risk clarification." },
      { version: "v1", status: "Active", changedAt: "Last week", note: "Current retention classifier." },
    ],
    evalMetrics: {
      agreement: "79%",
      agreementDelta: "+6% vs active",
      changedLabels: "6 / 24",
      changedLabelsNote: "Mostly warm vs at-risk",
      confidenceAvg: "0.75",
      confidenceDelta: "Up from 0.71",
    },
    evalRows: [
      {
        contactId: "contact-carlos",
        contact: "Carlos",
        expected: "vip_warm",
        active: "vip_cold",
        draft: "vip_warm",
        why: "Customer re-opened the conversation and asked about next steps.",
      },
    ],
  },
];

export function getJourneyStudioRecord(journeyKey: string) {
  return journeyStudioRecords.find((record) => record.journeyKey === journeyKey);
}
