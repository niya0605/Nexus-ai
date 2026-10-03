export interface Source {
  id: string;
  title: string;
  page: number;
  relevance: number;
  documentType: string;
  tags: string[];
  /** Short "last touched" label shown in the citation row, e.g. "Updated 2 days ago". */
  updatedLabel: string;
  /** Bold sub-heading atop the source preview's paper excerpt, e.g. "3.2 Q3 Roadmap Overview". */
  previewHeading: string;
  /** The paper excerpt's lead paragraph. */
  snippet: string;
  /** Bulleted callouts under the paper excerpt — the specific lines the answer cites. */
  previewPoints: string[];
}

export interface AnswerData {
  question: string;
  answer: string;
  keyPoints: string[];
  sources: Source[];
}

/**
 * Static, illustrative content for the /dashboard "Ask Nexus" demo.
 * There is no backend wiring here (Sprint 1B's real registration
 * endpoint exists, but chat/RAG endpoints don't yet) — this is a
 * frontend interaction preview, same spirit as the login/register
 * forms' "not yet connected" notices.
 */
export const MOCK_ANSWERS: AnswerData[] = [
  {
    question: "What's our Q3 revenue target?",
    answer:
      "Based on the Q3 planning documents, the team is targeting $2.4M in ARR by the end of the quarter, driven primarily by the enterprise tier launch.",
    keyPoints: [
      "Target: $2.4M ARR by end of Q3",
      "Primary driver: enterprise tier launch in August",
      "Secondary driver: expanded self-serve conversion",
    ],
    sources: [
      {
        id: "s1",
        title: "Q3 Roadmap v2.1",
        page: 14,
        relevance: 96,
        documentType: "PDF",
        tags: ["Planning", "Q3"],
        updatedLabel: "Updated 2 days ago",
        previewHeading: "3.2 Q3 Roadmap Overview",
        snippet:
          "The Q3 roadmap focuses on strengthening our core platform with AI search and deeper integrations, reflecting a $2.4M ARR target for the quarter.",
        previewPoints: [
          "AI-powered search (Phase 1) now targeted for July 2024",
          "Enterprise tier launch scheduled for August",
          "40% increase over Q2, driven by the enterprise motion",
        ],
      },
      {
        id: "s2",
        title: "Product Planning Doc",
        page: 6,
        relevance: 88,
        documentType: "Doc",
        tags: ["Product"],
        updatedLabel: "Updated 5 days ago",
        previewHeading: "1.4 Enterprise Tier Pricing",
        snippet:
          "Enterprise tier pricing was finalized at $2,400/mo, positioning it as the primary lever for reaching the Q3 revenue target.",
        previewPoints: ["Enterprise tier: $2,400/mo", "Primary lever for the Q3 ARR target"],
      },
      {
        id: "s3",
        title: "Leadership Meeting Notes",
        page: 23,
        relevance: 74,
        documentType: "Notes",
        tags: ["Leadership", "Q3"],
        updatedLabel: "Jun 2, 2024",
        previewHeading: "Leadership Sync — Q3 Targets",
        snippet:
          "Discussed Q3 targets in the leadership sync — agreed to prioritize enterprise motion over additional self-serve growth experiments.",
        previewPoints: ["Prioritize enterprise motion", "Self-serve experiments deprioritized this quarter"],
      },
    ],
  },
  {
    question: "Who owns the onboarding redesign?",
    answer:
      "The onboarding redesign is owned by the Product Design team, with engineering support from the Growth pod. It's scoped for delivery in the current sprint.",
    keyPoints: [
      "Owner: Product Design (Growth pod supporting)",
      "Scope: first-run flow through first successful answer",
      "Target: delivery this sprint",
    ],
    sources: [
      {
        id: "s4",
        title: "Onboarding Redesign Brief",
        page: 2,
        relevance: 93,
        documentType: "Doc",
        tags: ["Design", "Onboarding"],
        updatedLabel: "Updated 1 day ago",
        previewHeading: "Ownership & Scope",
        snippet: "Product Design owns the end-to-end onboarding redesign, from account creation through the first cited answer.",
        previewPoints: ["Owner: Product Design", "Scope: account creation → first cited answer"],
      },
      {
        id: "s5",
        title: "Sprint Planning Notes",
        page: 9,
        relevance: 81,
        documentType: "Notes",
        tags: ["Engineering"],
        updatedLabel: "Updated 3 days ago",
        previewHeading: "Growth Pod Allocation",
        snippet: "Growth pod allocated 1 engineer to support the onboarding redesign for the remainder of the sprint.",
        previewPoints: ["1 engineer allocated from Growth", "Support through end of sprint"],
      },
    ],
  },
];

export const SUGGESTED_QUESTIONS = MOCK_ANSWERS.map((a) => a.question).concat(
  "What did we decide about pricing?",
);
