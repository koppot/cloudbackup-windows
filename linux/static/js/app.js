document.addEventListener('DOMContentLoaded', () => {
  pollJobStatus();
  setInterval(pollJobStatus, 5000);
});

async function pollJobStatus() {
  try {
    const res = await fetch('/jobs/running-status');
    if (!res.ok) return;
    const job = await res.json();
    const banner = document.getElementById('live-job-banner');
    const text = document.getElementById('live-job-text');
    if (!banner || !text) return;

    if (job && job.job_name) {
      const lastLine = job.last_output && job.last_output.length > 0
        ? job.last_output[job.last_output.length - 1]
        : 'Running...';
      text.innerText = `Job running: ${job.job_name} (Run #${job.run_id}) — ${lastLine}`;
      banner.style.display = 'flex';
    } else {
      banner.style.display = 'none';
    }
  } catch (err) {
    console.error('Status poll error:', err);
  }
}
