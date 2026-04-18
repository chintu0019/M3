interface Props {
  value: string; // ISO YYYY-MM-DD
  onChange: (iso: string) => void;
  min: string;
  max: string;
}

function days(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 86400000);
}

export default function TimeSlider({ value, onChange, min, max }: Props) {
  const minD = days(min);
  const maxD = days(max);
  const curD = Math.min(Math.max(days(value), minD), maxD);
  const pct = maxD === minD ? 100 : ((curD - minD) / (maxD - minD)) * 100;

  return (
    <div className="m3-timeslider">
      <div className="m3-timeslider__row">
        <div className="m3-timeslider__label">TIME</div>
        <div className="m3-timeslider__value">as of {value}</div>
      </div>
      <div className="m3-timeslider__track">
        <div className="m3-timeslider__fill" style={{ width: `${pct}%` }} />
        <input
          type="range"
          min={minD}
          max={maxD}
          value={curD}
          onChange={(e) => {
            const d = parseInt(e.target.value, 10);
            const iso = new Date(d * 86400000).toISOString().slice(0, 10);
            onChange(iso);
          }}
        />
      </div>
      <div className="m3-timeslider__ends">
        <span>{min}</span>
        <span>now</span>
      </div>
    </div>
  );
}
