import { DOCS_URL } from "@/lib/links";

export function Footer() {
  return (
    <footer className="border-t border-[var(--border)] py-12 px-4 sm:px-6">
      <div className="max-w-6xl mx-auto">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="font-bold text-lg">MIRSAD MASR</span>
            </div>
            <p className="text-xs text-[var(--muted-foreground)]">
              MIT License · Made in 🇪🇬
            </p>
          </div>

          <nav className="flex flex-wrap items-center gap-4 text-sm text-[var(--muted-foreground)]">
            <a
              href={DOCS_URL}
              className="hover:text-[var(--foreground)] transition-colors"
            >
              Docs
            </a>
            <a
              href="#disclaimer"
              className="hover:text-[var(--foreground)] transition-colors"
            >
              Disclaimer
            </a>
            <a
              href="https://opensource.org/licenses/MIT"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-[var(--foreground)] transition-colors"
            >
              License
            </a>
          </nav>
        </div>

        <div
          id="disclaimer"
          className="mt-8 pt-6 border-t border-[var(--border)] text-xs text-[var(--muted-foreground)] space-y-1"
        >
          <p>
            MIRSAD MASR is not a financial advisor. Data accuracy depends on
            third-party providers. Indicative, delayed data only — not financial
            advice. See the project DISCLAIMER for full terms.
          </p>
          <p>
            © {new Date().getFullYear()} MIRSAD MASR contributors. MIT licensed.
          </p>
        </div>
      </div>
    </footer>
  );
}
