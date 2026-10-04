const LAYER_OPTIONS = [
  { id: 'requests', label: '311 Requests' },
  { id: 'highPriority', label: 'High Priority' },
  { id: 'communities', label: 'Calgary Communities' },
]

function MapLayersPanel({ layers, onChange }) {
  return (
    <div className="pointer-events-auto w-48 rounded-md border border-border bg-white p-3 shadow-sm">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text">
        Layers
      </h3>
      <ul className="space-y-1.5">
        {LAYER_OPTIONS.map((option) => {
          const checked = layers[option.id]
          return (
            <li key={option.id}>
              <label className="flex cursor-pointer items-center gap-2 text-sm text-text">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(event) => onChange(option.id, event.target.checked)}
                  className="h-3.5 w-3.5 rounded-sm border-border text-calgary-red accent-calgary-red focus:ring-calgary-red"
                />
                <span>{option.label}</span>
              </label>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export default MapLayersPanel
