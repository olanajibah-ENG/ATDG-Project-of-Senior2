/**
 * ProjectTestsPage.tsx   route:  /dashboard/projects/:project_id/tests
 * ---------------------------------------------------------------------------
 * The Test Generation UI is now a set of popups opened from the Dashboard
 * (see components/Tests/TestsModalHost.tsx). This route only keeps old links
 * working: it sends the user to the Dashboard and the popup opens there.
 */
import React from 'react';
import { Navigate, useParams } from 'react-router-dom';

const ProjectTestsPage: React.FC = () => {
  const { project_id = '' } = useParams<{ project_id: string }>();
  return <Navigate to={`/dashboard?testproject=${encodeURIComponent(project_id)}`} replace />;
};

export default ProjectTestsPage;