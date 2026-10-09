interface RouteStubProps {
  title: string;
  description: string;
}

/** Shared placeholder for the five Milestone-1 routes — the UI task replaces these. */
export function RouteStub({ title, description }: RouteStubProps) {
  return (
    <section className="route-stub">
      <h1>{title}</h1>
      <p>{description}</p>
      <p className="stub-tag">Milestone 1 stub — this screen is built by the UI task.</p>
    </section>
  );
}
