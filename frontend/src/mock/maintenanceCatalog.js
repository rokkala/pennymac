/** Demo/mock mirror of backend/lbp/maintenance.py allowlist (bundled via Vite ?raw). */
import feedJob from "../../../aws/glue/feed_job.py?raw";
import feedSpark from "../../../aws/glue/feed_spark_job.py?raw";
import vendorPull from "../../../aws/glue/vendor_pull_job.py?raw";
import glueJobs from "../../../backend/lbp/glue_jobs.py?raw";
import dispatch from "../../../backend/lbp/dispatch.py?raw";
import boardingSfn from "../../../aws/stepfunctions/boarding.asl.json?raw";
import lambdas from "../../../aws/lambdas/handlers.py?raw";
import feedNb from "../../../aws/glue/notebooks/feed_workbench.ipynb?raw";
import ruleNb from "../../../aws/glue/notebooks/rule_lab.ipynb?raw";

const ARTIFACTS = [
  { id: "feed-job", title: "lbp-feed", subtitle: "Board / replay one batch (driver)", path: "aws/glue/feed_job.py", kind: "python", group: "jobs", raw: feedJob },
  { id: "feed-spark-job", title: "lbp-feed-spark", subtitle: "Large full tapes (Spark)", path: "aws/glue/feed_spark_job.py", kind: "python", group: "jobs", raw: feedSpark },
  { id: "vendor-pull-job", title: "lbp-vendor-pull", subtitle: "SFTP / S3 pull into raw zone", path: "aws/glue/vendor_pull_job.py", kind: "python", group: "jobs", raw: vendorPull },
  { id: "glue-jobs", title: "lbp.glue_jobs", subtitle: "Shared entrypoints the Glue scripts call", path: "backend/lbp/glue_jobs.py", kind: "python", group: "shared", raw: glueJobs },
  { id: "dispatch", title: "lbp.dispatch", subtitle: "API / control plane starts Glue runs", path: "backend/lbp/dispatch.py", kind: "python", group: "shared", raw: dispatch },
  { id: "boarding-sfn", title: "Step Functions · boarding", subtitle: "Route → Glue → finalize → notify", path: "aws/stepfunctions/boarding.asl.json", kind: "json", group: "orchestration", raw: boardingSfn },
  { id: "lambdas", title: "Lambdas · handlers", subtitle: "Arrival, route, finalize, API, scheduler", path: "aws/lambdas/handlers.py", kind: "python", group: "orchestration", raw: lambdas },
  { id: "nb-feed-workbench", title: "Notebook · feed workbench", subtitle: "Dev dry-run — does not load loans", path: "aws/glue/notebooks/feed_workbench.ipynb", kind: "notebook", group: "notebooks", raw: feedNb },
  { id: "nb-rule-lab", title: "Notebook · rule lab", subtitle: "Dev rule tryout — does not change rules", path: "aws/glue/notebooks/rule_lab.ipynb", kind: "notebook", group: "notebooks", raw: ruleNb },
];

const cellsOf = (raw) => {
  const nb = JSON.parse(raw);
  return (nb.cells || []).map((c) => ({
    cell_type: c.cell_type || "code",
    source: Array.isArray(c.source) ? c.source.join("") : (c.source || ""),
  }));
};

export const listMaintenanceArtifacts = () =>
  ARTIFACTS.map(({ id, title, subtitle, path, kind, group }) => ({ id, title, subtitle, path, kind, group }));

export const getMaintenanceArtifact = (id) => {
  const a = ARTIFACTS.find((x) => x.id === id);
  if (!a) throw new Error(`unknown artifact: ${id}`);
  const content = a.kind === "notebook" ? cellsOf(a.raw) : a.raw;
  return { id: a.id, title: a.title, subtitle: a.subtitle, path: a.path, kind: a.kind, group: a.group, content };
};
