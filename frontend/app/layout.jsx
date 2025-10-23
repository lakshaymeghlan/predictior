import "./globals.css";
import Navbar from "./components/Navbar";

export const metadata = {
  title: "Predictor",
  description: "Market predictor dashboard",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="bg-gray-900 text-gray-100 min-h-screen">
        <Navbar />
        <main className="container mx-auto p-6">{children}</main>
      </body>
    </html>
  );
}
