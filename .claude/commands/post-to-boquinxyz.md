---
description: Add a new dashboard to boquin.xyz portfolio site
args:
  repo_url:
    description: GitHub repository URL for the new dashboard
    required: true
  title:
    description: Dashboard title (e.g., "EMFX Risk Diffusion")
    required: true
  emoji:
    description: Emoji icon for the dashboard card (e.g., "🌐")
    required: true
  description:
    description: Short description of the dashboard
    required: true
  dashboard_url:
    description: URL where the dashboard is hosted (optional, will infer from repo if not provided)
    required: false
---

You are helping to add a new dashboard card to the boquin.xyz portfolio website.

# Task

1. Clone or navigate to the boquin.xyz repository at https://github.com/DataVizHonduran/boquin.github.io
2. Add a new dashboard card to the index.html file with the following information:
   - Emoji: {{emoji}}
   - Title: {{title}}
   - Description: {{description}}
   - Dashboard URL: {{dashboard_url}} (if not provided, infer from repo_url by converting github.com/DataVizHonduran/REPO_NAME to datavizhonduran.github.io/REPO_NAME/)
   - Source Code URL: {{repo_url}}
3. Add the new card at the end of the dashboard grid, just before the closing `</div>` tag
4. Commit the changes with message: "Add {{title}} dashboard to portfolio"
5. Push to GitHub using SSH (git@github.com:DataVizHonduran/boquin.github.io.git)

# Important Notes

- The repository should be cloned to /tmp/boquin-repo if it doesn't exist
- Use SSH remote URL for pushing: git@github.com:DataVizHonduran/boquin.github.io.git
- Follow the existing HTML structure and formatting
- Include the Claude Code co-authorship footer in the commit message
- The dashboard grid is currently set to 4 columns

# Example Card Structure

```html
<article class="dashboard-card">
    <div class="card-header">
        <h3>{{emoji}} {{title}}</h3>
        <p>{{description}}</p>
    </div>
    <div class="card-actions">
        <a href="{{dashboard_url}}" class="btn btn-primary">Launch Dashboard</a>
        <a href="{{repo_url}}" class="btn btn-secondary">Source Code</a>
    </div>
</article>
```
