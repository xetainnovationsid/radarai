import { StudyViewerClient } from "@/components/StudyViewerClient";

export default async function StudyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <StudyViewerClient studyId={id} />;
}
