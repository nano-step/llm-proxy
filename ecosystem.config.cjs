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
      script: path.join(process.env.HOME, ".venvs/litellm/bin/litellm"),
      args: `--config ${path.join(CWD, "litellm_config.yaml")} --port ${process.env.LITELLM_PORT || "4000"}`,
      cwd: CWD,
      interpreter: "none",
      env: {
        GITLAB_PAT: process.env.GITLAB_PAT,
        LITELLM_PORT: process.env.LITELLM_PORT || "4000",
        LITELLM_MASTER_KEY: process.env.LITELLM_MASTER_KEY,
        DATABASE_URL: process.env.DATABASE_URL,
        STORE_MODEL_IN_DB: process.env.STORE_MODEL_IN_DB || "True",
        UI_USERNAME: process.env.UI_USERNAME || "admin",
        UI_PASSWORD: process.env.UI_PASSWORD,
        PYTHONPATH: CWD,
      },
      autorestart: true,
      max_restarts: 50,
      min_uptime: "5s",
      restart_delay: 3000,

      error_file: path.join(CWD, "litellm-error.log"),
      out_file: path.join(CWD, "litellm-out.log"),
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      watch: false,
    },
  ],
};
