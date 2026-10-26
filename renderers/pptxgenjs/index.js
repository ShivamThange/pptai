// Public Node CLI delegates to the same Python contract validator and adapter.
const {spawnSync}=require("child_process");
const path=require("path");
const args=process.argv.slice(2).map((arg,i) => i<2 ? path.resolve(arg) : arg);
const run=spawnSync(process.env.PPTAI_PYTHON || "python",["-m","renderers",...args,"--renderer","pptxgenjs"],
  {cwd:path.resolve(__dirname,"../.."),stdio:"inherit",windowsHide:true});
if (run.error) {console.error(run.error.message);process.exit(1);}
process.exit(run.status === null ? 1 : run.status);
