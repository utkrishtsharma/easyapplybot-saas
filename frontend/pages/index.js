import { useState } from 'react';

export default function Home() {
  const [positions, setPositions] = useState('');
  const [locations, setLocations] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    const response = await fetch('/api/submit-job', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        positions: positions.split(','),
        locations: locations.split(','),
      }),
    });
    if (response.ok) alert('Job application request submitted!');
  };

  const triggerPause = async () => {
    const response = await fetch('http://localhost:5002/pause', { method: 'POST' });
    if (response.ok) alert('Bot paused for 10 seconds');
  };

  const triggerCancel = async () => {
    const response = await fetch('http://localhost:5002/cancel', { method: 'POST' });
    if (response.ok) alert('Application cancelled');
  };

  return (
    <div>
      <h1>EasyApplyBot SaaS</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Positions (comma-separated):
          <input type="text" value={positions} onChange={(e) => setPositions(e.target.value)} />
        </label>
        <label>
          Locations (comma-separated):
          <input type="text" value={locations} onChange={(e) => setLocations(e.target.value)} />
        </label>
        <button type="submit">Apply to Jobs</button>
      </form>
      <div>
        <button onClick={triggerPause}>Pause Bot (Ctrl+P)</button>
        <button onClick={triggerCancel}>Cancel Application (Ctrl+C)</button>
      </div>
    </div>
  );
}