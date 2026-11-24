export const routes = {
  journeys: "/journeys",
  journeyStudio: (journeyKey: string) => `/journeys/${journeyKey}`,
  contactInspector: (contactId: string) => `/contacts/${contactId}`,
} as const;
