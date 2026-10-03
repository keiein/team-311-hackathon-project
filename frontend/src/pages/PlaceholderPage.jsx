function PlaceholderPage({ title, description }) {
  return (
    <div className="flex h-full flex-col bg-white">
      <header className="border-b border-border px-5 py-3">
        <h2 className="text-lg font-semibold text-text">{title}</h2>
        <p className="text-sm text-text-muted">{description}</p>
      </header>
      <div className="flex flex-1 items-center justify-center px-5">
        <p className="text-sm text-text-muted">
          This page is a placeholder and will be built in a later iteration.
        </p>
      </div>
    </div>
  )
}

export default PlaceholderPage
