# GitHub Pages Configuration

This document provides instructions for configuring GitHub Pages for the shekel documentation.

## Automatic Configuration (Recommended)

The GitHub Actions workflow will automatically deploy to the `gh-pages` branch. You just need to enable GitHub Pages in the repository settings.

### Steps:

1. Push the documentation changes to the `main` branch
2. Go to your GitHub repository settings
3. Navigate to **Settings** → **Pages**
4. Under **Source**, select:
   - **Source**: Deploy from a branch
   - **Branch**: `gh-pages`
   - **Folder**: `/ (root)`
5. Click **Save**

The site will be available at: `https://arieradle.github.io/shekel/`

## Manual Configuration (Alternative)

If you prefer to configure using the `gh` CLI:

```bash
# Enable GitHub Pages with gh-pages branch
gh repo edit --enable-pages --pages-branch gh-pages --pages-path /
```

## Verification

After the first deployment:

1. Check the **Actions** tab for the deployment workflow
2. Wait for the workflow to complete
3. Visit `https://arieradle.github.io/shekel/` to see your docs

## Troubleshooting

### Pages Not Showing

- Ensure the workflow completed successfully in the Actions tab
- Check that the `gh-pages` branch was created
- Verify Pages is enabled in Settings → Pages
- Wait 1-2 minutes for GitHub's CDN to update

### Build Failures

- Check the workflow logs in the Actions tab
- Ensure `mkdocs.yml` is valid
- Verify all documentation files exist

### Custom Domain (Optional)

To use a custom domain:

1. Add a `CNAME` file to the `docs/` directory with your domain
2. Update the workflow to enable CNAME:
   ```yaml
   - name: Deploy to GitHub Pages
     uses: peaceiris/actions-gh-pages@v3
     with:
       github_token: ${{ secrets.GITHUB_TOKEN }}
       publish_dir: ./site
       cname: docs.yourdomain.com
   ```
3. Configure DNS with your domain provider

## Deployment Workflow

The documentation deploys automatically when:

- Changes are pushed to `main` branch
- Changes are made to `docs/**`, `mkdocs.yml`, or `.github/workflows/docs.yml`
- The workflow is manually triggered

## Local Preview

Test the documentation locally before pushing:

```bash
# Install mkdocs-material
pip install mkdocs-material

# Serve locally
mkdocs serve

# Open http://127.0.0.1:8000/ in your browser
```

## Next Steps

Once configured:
1. Documentation updates will deploy automatically
2. Visit your docs at `https://arieradle.github.io/shekel/`
3. Share the link in your README
