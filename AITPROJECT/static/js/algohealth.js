async function updateAlgoHealth() {
    try {
      const res = await fetch('/algo/health');
      if (!res.ok) throw new Error('Network response was not ok');
      const { models_loaded, task_running, healthy } = await res.json();

      const elModels  = document.getElementById('algo-models-loaded');
      const elTask    = document.getElementById('algo-task-running');
      const elHealthy = document.getElementById('algo-healthy');
      const elTime    = document.getElementById('algo-last-checked');

      // update badges...
      if (models_loaded) {
        elModels.textContent = 'OK';
        elModels.className   = 'badge bg-success';
      } else {
        elModels.textContent = 'NOTOK';
        elModels.className   = 'badge bg-danger';
      }

      if (task_running) {
        elTask.textContent = 'OK';
        elTask.className   = 'badge bg-success';
      } else {
        elTask.textContent = 'NOTOK';
        elTask.className   = 'badge bg-danger';
      }

      if (healthy) {
        elHealthy.textContent = 'OK';
        elHealthy.className   = 'badge bg-success';
      } else {
        elHealthy.textContent = 'NOTOK';
        elHealthy.className   = 'badge bg-danger';
      }

      // update last-checked timestamp
      const now = new Date();
      elTime.textContent = now.toLocaleTimeString();  // e.g. "19:52:04"
    } catch (err) {
      console.error('Failed to fetch /algo/health:', err);
    }
  }

  updateAlgoHealth();
  setInterval(updateAlgoHealth, 30000);