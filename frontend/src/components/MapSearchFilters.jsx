function MapSearchFilters({
  search,
  onSearchChange,
  crewFilter,
  onCrewFilterChange,
  priorityFilter,
  onPriorityFilterChange,
}) {
  return (
    <div className="pointer-events-auto flex flex-wrap items-center justify-end gap-2">
      <input
        type="search"
        value={search}
        onChange={(event) => onSearchChange(event.target.value)}
        placeholder="Search address or ticket..."
        className="w-52 rounded-md border border-border bg-white px-3 py-1.5 text-sm text-text shadow-sm placeholder:text-neutral-400 focus:border-calgary-red focus:outline-none focus:ring-1 focus:ring-calgary-red"
      />

      <select
        value={crewFilter}
        onChange={(event) => onCrewFilterChange(event.target.value)}
        aria-label="Filter by crew"
        className="rounded-md border border-border bg-white px-2.5 py-1.5 text-sm text-text shadow-sm focus:border-calgary-red focus:outline-none focus:ring-1 focus:ring-calgary-red"
      >
        <option value="all">All Crews</option>
      </select>

      <select
        value={priorityFilter}
        onChange={(event) => onPriorityFilterChange(event.target.value)}
        aria-label="Filter by priority"
        className="rounded-md border border-border bg-white px-2.5 py-1.5 text-sm text-text shadow-sm focus:border-calgary-red focus:outline-none focus:ring-1 focus:ring-calgary-red"
      >
        <option value="all">All Priorities</option>
      </select>
    </div>
  )
}

export default MapSearchFilters
