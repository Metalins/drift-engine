import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Products — Metalins";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "#09090b",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "80px",
        }}
      >
        <div
          style={{
            color: "#71717a",
            fontSize: 18,
            letterSpacing: "0.15em",
            textTransform: "uppercase",
            marginBottom: 24,
            fontFamily: "monospace",
          }}
        >
          metalins.com / products
        </div>
        <div
          style={{
            color: "#fafafa",
            fontSize: 64,
            fontWeight: 700,
            lineHeight: 1.1,
            marginBottom: 24,
          }}
        >
          Products
        </div>
        <div
          style={{
            color: "#a1a1aa",
            fontSize: 28,
            lineHeight: 1.4,
            maxWidth: 800,
          }}
        >
          What we build and publish at Metalins.
        </div>
        <div
          style={{
            color: "#52525b",
            fontSize: 18,
            marginTop: 32,
          }}
        >
          Metalins — Independent Research Lab
        </div>
      </div>
    ),
    size
  );
}
