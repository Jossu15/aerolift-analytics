import PortfolioPage from "@/components/PortfolioPage";

export const metadata = {
  title: "Portfolio — AeroLift Analytics",
};

export default function PortfolioRoute() {
  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 py-6">
        <PortfolioPage />
      </div>
    </main>
  );
}