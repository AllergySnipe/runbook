import { Link } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { Term } from "../components/ui.jsx";
import { LOOP_STEPS } from "../content/copy.js";

// Extra depth per stage, beyond the one-paragraph summary in copy.js.
const DEEP = {
  triage: {
    why: "A prompted classifier, not a fine-tuned model — the failure modes are few and the labels are cheap to reason about. Recall on 'real incident' is deliberately traded against precision: routing a genuine incident to 'noise' is the expensive mistake.",
    detail: (
      <>
        Input is normalised first: an <Term term="alertmanager">Alertmanager</Term> webhook payload
        (dict or JSON string) or free text both collapse to the same shape. The four lanes are{" "}
        <code>known-runbook</code>, <code>novel-incident</code>, <code>noise-or-flapping</code>,{" "}
        <code>need-more-info</code>. The first two proceed; a <Term term="novel-incident">novel</Term>{" "}
        incident proceeds with a note that the retrieved runbook is a weak prior.
      </>
    ),
  },
  retrieve: {
    why: "Pure vector search misses exact identifiers (a metric name, an error string); pure keyword search misses paraphrase. Fusing both, then reranking, gets hit@3 to 1.00 on the golden set — where pure vector sat lower.",
    detail: (
      <>
        <Term term="hybrid-search">Hybrid search</Term>: <Term term="pgvector">pgvector</Term> cosine
        similarity in parallel with Postgres full-text, combined by{" "}
        <Term term="rrf">Reciprocal Rank Fusion</Term>, then a{" "}
        <Term term="cross-encoder">cross-encoder rerank</Term> of the top 30 into the top-k. The
        matched chunk is often a symptom section, so the full top runbook is hydrated from disk to
        put the Remediation section in context. A parallel lookup against{" "}
        <Term term="incident-memory">incident memory</Term> surfaces a past incident whose root
        cause a human confirmed — shown as context, never a grounding source, and only when the
        new alert closely matches a recurrence.
      </>
    ),
  },
  investigate: {
    why: "A framework's agentic tool-runner hides the loop — and the loop is exactly where the safety branches belong. So it's a plain while-loop: ask, execute, feed back, repeat, cap at 8.",
    detail: (
      <>
        The four <Term term="read-only-tools">read-only tools</Term> — <code>query_metrics</code>,{" "}
        <code>search_logs</code>, <code>get_recent_deploys</code>,{" "}
        <code>get_service_dependencies</code> — run against <Term term="sim">the sim</Term>, a
        deterministic fixture environment. Every call is checked against an allowlist before it runs;
        a call to anything else is refused and recorded (<strong>S2</strong>). Tool output goes back
        into the prompt inside a labelled, delimited block — <Term term="redaction">untrusted data</Term>,
        never instructions (<strong>S4</strong>).
      </>
    ),
  },
  synthesize: {
    why: "The model is asked for a fixed JSON shape, validated with Pydantic. Then grounding is enforced mechanically — the model can't talk its way past it.",
    detail: (
      <>
        Each remediation step carries a <code>runbook_quote</code>. A check confirms a contiguous
        fragment of that quote appears verbatim in the retrieved runbook (under loose normalisation).
        Failures trigger one regeneration with the specific violations named; steps still ungrounded
        are dropped; if nothing remains, the run becomes an escalation. This is{" "}
        <Term term="grounding">S3</Term>.
      </>
    ),
  },
  guardrail: {
    why: "The model's own read-only / state-changing label is not trusted. A real run caught the diagnosis model calling a '…restart it' step read-only — the independent classifier corrected it.",
    detail: (
      <>
        <Term term="action-classification">Action classification</Term> combines the runbook's own{" "}
        <code>[read-only]</code> / <code>[state-changing]</code> tags, a high-precision mutation-verb
        scan, and a fail-safe to state-changing. A cheap{" "}
        <Term term="second-pass">second-model pass</Term> can only tighten — upgrade a step, flag one
        as unsupported — never loosen. The run's <Term term="disposition">disposition</Term> falls
        out: <code>auto</code>, <code>needs-approval</code>, or <code>escalate</code>.
      </>
    ),
  },
  approve: {
    why: "The gate is a persisted state machine, not a function that blocks on a human. A needs-approval run is rows in Postgres; a separate human-initiated command transitions them.",
    detail: (
      <>
        <code>compute_status(disposition, approval_states)</code> is a{" "}
        <Term term="state-machine">pure function</Term> with an exhaustive unit table — that is where
        the <Term term="approval-gate">S1</Term> guarantee is pinned. The only code that writes an
        <code> approved</code> state is <code>resolve_approvals()</code>, reachable only from{" "}
        <code>runbook approve</code> / the dashboard. The loop has no path to it.
      </>
    ),
  },
  record: {
    why: "One row per run is the audit record and, later, the flywheel: a human's root-cause correction becomes a new golden eval case and an entry in incident memory.",
    detail: (
      <>
        The <Term term="audit-record">audit row</Term> (<strong>S6</strong>) captures the trigger,
        the retrieved set, every tool call and its result, the proposal, the guardrail verdict, token
        usage, and each approval decision with who and when.
      </>
    ),
  },
};

export default function HowItWorks() {
  return (
    <div className="space-y-16">
      <header>
        <p className="font-mono text-[0.7rem] font-medium uppercase tracking-[0.16em] text-[var(--color-accent)]">
          How it works
        </p>
        <h1 className="font-display mt-3 max-w-3xl text-[2.1rem] font-medium leading-[1.15] tracking-[-0.02em] sm:text-[2.6rem]">
          A thin, explicit orchestration — so the safety branches are visible
        </h1>
        <div className="prose-col mt-6">
          <p>
            There is <Term term="no-framework">no agent framework</Term>. The whole loop is roughly
            two hundred lines of Python you can read top to bottom. That's a deliberate choice: a
            framework's tool-runner would abstract away the exact place where every safety decision is
            made. Below is each stage, what it does, and why it's built the way it is.
          </p>
        </div>
      </header>

      <nav className="flex flex-wrap gap-2">
        {LOOP_STEPS.map((s) => (
          <a
            key={s.key}
            href={`#${s.key}`}
            className="rounded-full border px-3 py-1 text-xs text-[var(--color-ink-muted)] hover:border-[var(--color-border-strong)] hover:text-[var(--color-ink)]"
          >
            {s.n}. {s.title}
          </a>
        ))}
      </nav>

      <div className="space-y-14">
        {LOOP_STEPS.map((s) => {
          const d = DEEP[s.key];
          return (
            <section key={s.key} id={s.key} className="scroll-mt-24">
              <div className="flex items-baseline gap-3">
                <span className="font-mono text-sm text-[var(--color-accent)]">§{s.n}</span>
                <h2 className="font-display text-[1.5rem] font-medium tracking-[-0.015em]">
                  {s.title}
                </h2>
                {s.safety && (
                  <span className="inline-flex items-center gap-1 rounded bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[0.65rem] font-semibold text-[var(--color-accent)]">
                    <ShieldCheck size={11} /> {s.safety}
                  </span>
                )}
              </div>
              <div className="prose-col mt-3">
                <p>{s.body}</p>
                <p>{d.detail}</p>
              </div>
              <div className="prose-col mt-3 rounded-lg border-l-2 border-[var(--color-accent)] bg-[var(--color-surface-2)] py-2 pl-4 pr-3">
                <p className="!mb-0 text-[0.85rem]">
                  <span className="font-semibold text-[var(--color-ink)]">Why this way — </span>
                  {d.why}
                </p>
              </div>
            </section>
          );
        })}
      </div>

      <footer className="border-t pt-8">
        <p className="prose-col text-[0.9rem] text-[var(--color-ink-muted)]">
          Every one of these branches is checked by the{" "}
          <Term term="golden-set">golden eval set</Term> — the{" "}
          <Term term="hard-check">hard checks</Term> must be 100%, and a{" "}
          <Term term="regression-gate">regression gate</Term> blocks silent quality drops between
          commits.{" "}
          <Link to="/evals" className="text-[var(--color-accent)] hover:underline">
            See the scorecard →
          </Link>
        </p>
      </footer>
    </div>
  );
}
