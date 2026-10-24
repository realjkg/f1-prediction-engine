/**
 * Privacy and About. States what the app keeps and what it does not, in the
 * same terms as docs/PRIVACY.md. Claims stay limited to what the code
 * controls; hosting and network logs are named as outside controls.
 */
export function AboutPage() {
  return (
    <section className="about" aria-labelledby="about-title">
      <h1 id="about-title">Privacy and about</h1>
      <p className="screen-intro">
        Pit Wall predicts Formula 1 race winners from historical data and shows the evidence behind
        each number. It is advisory only: no accounts, no betting, no money.
      </p>

      <h2>No accounts, nothing saved about you</h2>
      <ul className="limit-list">
        <li>There is no sign-up, login, profile, email or password anywhere in the app.</li>
        <li>The app sets no cookies and stores nothing about you in your browser. Picks and scores in the
          Rewind game last only until you reload the page.</li>
        <li>Data an older version saved under <code>pitwall.record.v1</code> is deleted when the app
          opens. Nothing else on this site's storage is touched.</li>
        <li>No analytics, tracking pixels, fingerprinting or session recording.</li>
        <li>The offline cache holds only the app's own files, never predictions or anything about you.</li>
      </ul>

      <h2>What is kept</h2>
      <table className="win-table retention-table">
        <caption>Retention by kind of data</caption>
        <thead>
          <tr><th scope="col">Data</th><th scope="col">Where</th><th scope="col">Kept</th></tr>
        </thead>
        <tbody>
          <tr><th scope="row">Your picks, scores, preferences</th><td>This page's memory</td><td>Until reload</td></tr>
          <tr><th scope="row">F1 results and qualifying</th><td>Server dataset</td><td>Until replaced by a reviewed refresh</td></tr>
          <tr><th scope="row">Predictions and model evidence</th><td>Server ledger (append-only)</td><td>Kept; contains no visitor data</td></tr>
          <tr><th scope="row">Request counts by route and status</th><td>Server metrics, in memory</td><td>Until the server restarts</td></tr>
          <tr><th scope="row">Per-visitor request logs (IP address, browser)</th><td>Not written by the app</td><td>No access logs; critical errors only; see below</td></tr>
        </tbody>
      </table>
      <p className="data-note">
        The app's own servers keep no access logs. Their error log is limited to critical server
        faults, which can include the address of the request that caused one. A hosting provider,
        CDN or network in front of the site may keep its own logs, which this code cannot switch off. Check the host's settings before
        saying a deployment keeps no visitor data.
      </p>

      <h2>How predictions are labeled</h2>
      <ul className="limit-list">
        <li><strong>HISTORICAL</strong>: a finished race replayed with only the data from before it.</li>
        <li><strong>PRE-RACE</strong>: an upcoming race. None are available until current-season data is added.</li>
        <li><strong>SYNTHETIC</strong>: invented demo data, never a real race.</li>
        <li><strong>LIVE</strong>: only when a licensed timing feed is connected with fresh data.</li>
        <li><strong>UNAVAILABLE</strong>: the app explains what is missing instead of guessing.</li>
      </ul>
      <p className="data-note">
        Data: Jolpica F1 (CC BY-NC-SA 4.0), non-commercial use. Formula 1 is a trademark of its owners;
        this project is not affiliated with them.
      </p>
    </section>
  );
}
