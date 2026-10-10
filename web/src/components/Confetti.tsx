interface ConfettiProps {
  show: boolean;
}

/**
 * CSS confetti burst for the exact-podium moment. Deterministic shard layout
 * (precomputed constants, no Math.random) so tests and snapshots are stable;
 * animation itself runs via CSS and honors prefers-reduced-motion.
 */
const SHARDS = Array.from({ length: 18 }, (_, i) => ({
  left: (i * 53) % 100,
  delay: (i % 6) * 0.08,
  duration: 0.9 + ((i * 7) % 5) * 0.12,
  hue: ["teal", "papaya", "crimson", "silver"][i % 4],
}));

export function Confetti({ show }: ConfettiProps) {
  if (!show) return null;
  return (
    <div className="confetti" aria-hidden="true">
      {SHARDS.map((shard, index) => (
        <span
          key={index}
          className={`confetti-shard is-${shard.hue}`}
          style={{
            left: `${shard.left}%`,
            animationDelay: `${shard.delay}s`,
            animationDuration: `${shard.duration}s`,
          }}
        />
      ))}
    </div>
  );
}
