import { useNavigate } from "react-router-dom";

import { StudentWorkspace } from "./workspace/StudentWorkspace";

export function StudentRoutes() {
  const navigate = useNavigate();
  return <StudentWorkspace onNavigateTo={navigate} />;
}

export default StudentRoutes;
