import DashboardGrid from "@/components/DashboardGrid";

export const metadata = {
  title: "Dashboard — AeroLift Analytics",
};

export default function DashboardPage() {
  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 py-6">
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">
            AeroLift Analytics
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Monitoreo continuo de liquid loading
          </p>
        </header>
        <DashboardGrid />
      </div>
    </main>
  );
}
