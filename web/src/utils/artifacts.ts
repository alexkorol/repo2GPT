import JSZip from "jszip";
import { JobArtifacts } from "../types";

export async function createArtifactArchive(
  jobId: string,
  artifacts: JobArtifacts
): Promise<Blob> {
  const zip = new JSZip();
  zip.file(`repomap_${jobId}.txt`, artifacts.repomap);
  const chunksFolder = zip.folder("chunks");
  artifacts.chunks.forEach((chunk) => {
    const padded = String(chunk.index).padStart(4, "0");
    chunksFolder?.file(`chunk_${padded}.md`, chunk.content);
  });
  if (artifacts.warnings && artifacts.warnings.length > 0) {
    zip.file(
      "warnings.txt",
      artifacts.warnings.map((warning) => `- ${warning}`).join("\n")
    );
  }
  if (artifacts.token_totals) {
    zip.file(
      "token_summary.json",
      JSON.stringify(artifacts.token_totals, null, 2)
    );
  }
  return zip.generateAsync({ type: "blob" });
}
