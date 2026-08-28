import DashboardGrid from "@/components/DashboardGrid";
import Link from "next/link";

export const metadata = {
  title: "Dashboard — AeroLift Analytics",
};

export default function DashboardPage() {
  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 py-6">
        <header className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              AeroLift Analytics
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Monitoreo continuo de liquid loading
            </p>
          </div>
          <Link
            href="/portfolio"
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 transition"
          >
            Portfolio Optimizer →
          </Link>
        </header>
        <DashboardGrid />
      </div>
    </main>
  );
}
