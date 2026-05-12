import { nativeImage } from "electron";

function svgToDataUrl(svg: string): string {
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
}

export function createPetTrayIcon(isMac: boolean) {
  const svg = isMac
    ? `
      <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">
        <circle cx="11" cy="11" r="8" fill="#000000"/>
        <circle cx="8.3" cy="9.3" r="1.2" fill="#ffffff"/>
        <circle cx="13.7" cy="9.3" r="1.2" fill="#ffffff"/>
        <path d="M7.8 13.5C8.9 14.8 10 15.4 11 15.4c1.2 0 2.3-.7 3.4-1.9" stroke="#ffffff" stroke-width="1.7" stroke-linecap="round" fill="none"/>
      </svg>
    `
    : `
      <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
        <defs>
          <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#ff9f4a"/>
            <stop offset="100%" stop-color="#ff5b37"/>
          </linearGradient>
        </defs>
        <circle cx="16" cy="16" r="13" fill="url(#g)"/>
        <circle cx="11.5" cy="13.2" r="2" fill="#fff7e8"/>
        <circle cx="20.5" cy="13.2" r="2" fill="#fff7e8"/>
        <path d="M11.4 19.2C12.7 21 14.3 21.9 16 21.9c1.8 0 3.4-.9 4.7-2.7" stroke="#fff7e8" stroke-width="2.4" stroke-linecap="round" fill="none"/>
      </svg>
    `;

  const image = nativeImage.createFromDataURL(svgToDataUrl(svg));
  if (isMac) {
    image.setTemplateImage(true);
  }
  return image;
}
