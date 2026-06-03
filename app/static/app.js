function renderProgress(job) {
  const total = job.total_bytes || 1;
  const percent = Math.min(100, Math.round((job.downloaded_bytes / total) * 100));
  const currentTotal = job.current_file_total_bytes || 1;
  const currentPercent = Math.min(100, Math.round((job.current_file_bytes / currentTotal) * 100));
  return `
    <article class="job-card">
      <div class="section-header">
        <div>
          <h3>${job.repo_id}</h3>
          <p class="muted">${job.status} • ${job.current_file || 'waiting for worker'}</p>
        </div>
        <div class="button-row">
          <button data-job-action="pause" data-job-id="${job.id}">Pause</button>
          <button data-job-action="resume" data-job-id="${job.id}">Resume</button>
          <button data-job-action="cancel" data-job-id="${job.id}">Cancel</button>
        </div>
      </div>
      <div class="progress-block">
        <label>Total ${percent}%</label>
        <progress value="${job.downloaded_bytes}" max="${total}"></progress>
      </div>
      <div class="progress-block">
        <label>Current file ${currentPercent}%</label>
        <progress value="${job.current_file_bytes}" max="${currentTotal}"></progress>
      </div>
      <p class="muted">Speed: ${(job.speed_bytes_per_second / 1024 / 1024).toFixed(2)} MiB/s • ETA: ${job.eta_seconds ?? 'n/a'}s</p>
      <p class="muted">Target: ${job.target_path}</p>
      ${job.error_message ? `<p class="alert error">${job.error_message}</p>` : ''}
      ${job.failure_reason ? `<p class="alert warning">${job.failure_reason}</p>` : ''}
    </article>
  `;
}

async function refreshQueue() {
  const container = document.querySelector('[data-queue-page="true"]');
  if (!container) {
    return;
  }

  const response = await fetch('/api/downloads/queue');
  const payload = await response.json();
  container.innerHTML = payload.jobs.map(renderProgress).join('') || '<p class="muted">Queue is empty.</p>';

  document.querySelectorAll('[data-job-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      await fetch(`/api/downloads/${button.dataset.jobId}/${button.dataset.jobAction}`, { method: 'POST' });
      refreshQueue();
    });
  });
}

function filterRepoTable() {
  const input = document.getElementById('file-filter');
  const rows = document.querySelectorAll('#repo-file-table tbody tr');
  if (!input || rows.length === 0) {
    return;
  }

  const applyFilter = () => {
    const value = input.value.trim().toLowerCase();
    rows.forEach((row) => {
      const path = row.dataset.path.toLowerCase();
      row.hidden = value.length > 0 && !path.includes(value.replace('*', ''));
    });
  };

  input.addEventListener('input', applyFilter);
  document.getElementById('select-all-files')?.addEventListener('click', () => {
    rows.forEach((row) => {
      if (!row.hidden) {
        row.querySelector('input[type="checkbox"]').checked = true;
      }
    });
  });
  document.getElementById('clear-all-files')?.addEventListener('click', () => {
    rows.forEach((row) => {
      row.querySelector('input[type="checkbox"]').checked = false;
    });
  });
  document.querySelectorAll('[data-select-pattern]').forEach((button) => {
    button.addEventListener('click', () => {
      const pattern = button.dataset.selectPattern.toLowerCase();
      rows.forEach((row) => {
        row.querySelector('input[type="checkbox"]').checked = row.dataset.path.toLowerCase().includes(pattern);
      });
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  filterRepoTable();
  if (document.querySelector('[data-queue-page="true"]')) {
    refreshQueue();
    window.setInterval(refreshQueue, 2000);
  }
});
