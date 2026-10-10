import { ResourceView } from "../components/EngineError";
import { useEngineClient, useResource } from "../lib/engine";

/**
 * Observability — the engine's redacted event log and Prometheus counters,
 * served live. Nothing here is fabricated client-side: an unreachable engine
 * shows the typed error surface, not a pretend signal feed.
 */
export function ObservabilityPage() {
  const client = useEngineClient();
  const events = useResource(() => client.getEvents(), []);
  const metrics = useResource(() => client.getMetrics(), []);

  return (
    <section className="observability" aria-label="Observability">
      <h1>Observability</h1>
      <p className="screen-intro">
        The engine's closed-signal event log — redacted at creation — and its Prometheus counters, exactly as served.
      </p>

      <ResourceView
        resource={events}
        context="Event log"
        ready={(page) => (
          <section aria-label="Event log" className="event-log">
            <h2>
              Events ({page.events.length} of {page.total})
            </h2>
            {page.events.length === 0 ? (
              <p className="empty-state">No events recorded yet — lock a race to generate engine signals.</p>
            ) : (
              <table className="standings-table">
                <thead>
                  <tr>
                    <th scope="col">Signal</th>
                    <th scope="col">Status</th>
                    <th scope="col">When</th>
                    <th scope="col">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {page.events.map((event, index) => (
                    <tr key={`${event.occurredAt}-${event.signal}-${index}`}>
                      <th scope="row">{event.signal}</th>
                      <td>{event.status}</td>
                      <td>{event.occurredAt}</td>
                      <td>
                        <code className="event-detail">{JSON.stringify(event.detail)}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        )}
      />

      <ResourceView
        resource={metrics}
        context="Prometheus metrics"
        ready={(text) => (
          <section aria-label="Prometheus metrics" className="metrics-panel">
            <h2>/metrics</h2>
            <pre className="metrics-raw">
              <code>{text}</code>
            </pre>
          </section>
        )}
      />
    </section>
  );
}
