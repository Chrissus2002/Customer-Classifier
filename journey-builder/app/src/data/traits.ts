export type TraitSummary = {
  key: string;
  label: string;
  resolver: string;
  coverage: string;
  values: string;
  usedFor: string;
};

export type TraitClassifierSummary = {
  name: string;
  trait: string;
  version: string;
  outputs: string;
  status: string;
  note: string;
};

export const traitSummaries: TraitSummary[] = [
  {
    key: "customer_type",
    label: "Customer Type",
    resolver: "Trait Classifier",
    coverage: "82%",
    values: "wholesale / retail / unknown",
    usedFor: "Wholesale vs retail journey split",
  },
  {
    key: "preferred_language",
    label: "Preferred Language",
    resolver: "Imported rule",
    coverage: "94%",
    values: "es / en / unknown",
    usedFor: "LATAM journey routing",
  },
  {
    key: "is_existing_customer",
    label: "Existing Customer",
    resolver: "Imported attribute",
    coverage: "61%",
    values: "true / false / unknown",
    usedFor: "Retention and recovery targeting",
  },
];

export const traitClassifierSummaries: TraitClassifierSummary[] = [
  {
    name: "Customer Type Classifier",
    trait: "customer_type",
    version: "v1",
    outputs: "wholesale / retail / unknown",
    status: "active",
    note: "Simple per-chat classifier, separate from Journey classification.",
  },
];

export const traitActivity = [
  "A trait is a resolved attribute on the provided chat_id.",
  "Resolve traits from imported data, rules, manual edits, or a Trait Classifier.",
  "Trait Classifiers are first-class classifiers and are not part of any Journey.",
  "Trait evidence should be inspectable before operators trust routing.",
];
