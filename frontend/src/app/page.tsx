import Link from "next/link";

export default function Home() {
  return (
    <main className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">
          AeroLift Analytics
        </h1>
        <p className="text-gray-500 mb-8 max-w-md">
          Plataforma de monitoreo continuo de liquid loading para pozos de gas
          maduros. Fisica de flujo metaestable integrada.
        </p>
        <Link
          href="/dashboard"
          className="inline-block bg-blue-600 text-white px-6 py-3 rounded-lg font-medium hover:bg-blue-700 transition"
        >
          Ir al Dashboard
        </Link>
      </div>
    </main>
  );
}
