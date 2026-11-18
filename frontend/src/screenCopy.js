/** Screen names and the one-line job on each page. */

export const SCREEN = {
  overview: { label: "Overview", sub: "What is due, late, or stuck, and the queues that belong to you." },
  guide: { label: "How it works", sub: "The path from a new seller to a boarded loan." },
  monitor: { label: "Monitor", sub: "Live loads, history, and pipeline steps — open a batch to act." },
  imports: { label: "File loads", sub: "Upload a file or open a batch to pause, fix schema, or replay." },
  deliveries: { label: "Delivery schedule", sub: "See who is late and who is due next." },
  sources: { label: "Vendors", sub: "Set up a seller's files and how their columns map." },
  exceptions: { label: "Loans to fix", sub: "" },
  rules: { label: "Rules", sub: "Checks that hold a loan. Drafts need a second person before they go live." },
  analytics: { label: "Analytics", sub: "What boarded, what is still held, and which seller is driving it." },
  governance: { label: "Policy", sub: "Who may auto-apply a fix, and the audit of every change." },
  maintenance: { label: "Maintenance", sub: "Jobs the platform team can run." },
  personas: { label: "Personas", sub: "Who can sign in, and which screens they see." },
};

export function exceptionDeskSub({ acceptOnly = false, monitoringDesk = false } = {}) {
  if (acceptOnly) return "Accept or return fixes someone else submitted.";
  if (monitoringDesk) return "Confirm a suggested fix, or submit a regulated field for a reviewer.";
  return "Clear a false positive or reject the loan.";
}
