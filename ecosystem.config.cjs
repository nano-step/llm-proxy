const fs = require("fs");
const path = require("path");

const CWD = __dirname;
const envFile = path.join(CWD, ".env");
if (fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile, "utf8").split("\n")) {
    const m = line.match(/^([^#=]+)=(.*)$/);
    if (m) process.env[m[1].trim()] = m[2].trim();
  }
}

module.exports = {
  apps: [
    {
      name: "litellm-proxy",
      script: path.join(process.env.HOME, ".local/bin/litellm"),
      args: `--config ${path.join(CWD, "litellm_config.yaml")} --port ${process.env.LITELLM_PORT || "4000"} --num_workers 1`,
      cwd: CWD,
      interpreter: "none",
      env: {
        GITLAB_PAT: process.env.GITLAB_PAT,
        LITELLM_PORT: process.env.LITELLM_PORT || "4000",
        LITELLM_MASTER_KEY: process.env.LITELLM_MASTER_KEY,
      },
      autorestart: true,
      max_restarts: 10,
      min_uptime: "10s",
      restart_delay: 5000,

      error_file: path.join(CWD, "litellm-error.log"),
      out_file: path.join(CWD, "litellm-out.log"),
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      watch: false,
    },
  ],
};
