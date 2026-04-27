export default {
  async scheduled(_event, env, _ctx) {
    const url = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/${env.GH_WORKFLOW}/dispatches`;

    const resp = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cf-train-cron",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    });

    if (resp.ok) {
      console.log(`[OK] workflow_dispatch triggered (${resp.status})`);
    } else {
      const body = await resp.text();
      console.error(`[ERROR] GitHub API ${resp.status}: ${body}`);
    }
  },
};
