import { useEffect, useState, type FormEvent } from "react";
import {
  Alert, Badge, Button, Card, Checkbox, Container, Group, Loader,
  Select, Stack, Table, Text, Textarea, TextInput, Title,
} from "@mantine/core";
import { useLocation } from "react-router-dom";

import { http } from "../../../lib/http";
import { PageHeader } from "../../../ui/components/PageHeader";

type LeaveRequest = {
  id: number;
  category: string;
  start_date: string;
  end_date: string;
  requested_days: string;
  purpose: string;
  status: string;
  request_type: string;
  final_decision?: string;
};

type LeavePolicy = {
  id: number;
  category: string;
  annual_entitlement: string;
  employee_scope: string;
  enabled: boolean;
};

type ListResponse<T> = { results: T[] };

const categories = [
  { value: "CL", label: "Casual Leave (CL)" },
  { value: "RH", label: "Restricted Holiday (RH)" },
  { value: "SCL", label: "Special Casual Leave (SCL)" },
  { value: "EL", label: "Earned Leave (EL)" },
  { value: "COL", label: "Commuted Leave (COL)" },
  { value: "VL", label: "Vacation Leave (VL)" },
];

function getError(error: unknown): string {
  const candidate = error as { response?: { data?: { detail?: string; error?: { message?: string } } } };
  return candidate?.response?.data?.detail
    ?? candidate?.response?.data?.error?.message
    ?? "The request could not be completed. Check the API service and your access.";
}

export default function ELMPage() {
  const { pathname } = useLocation();
  const section = pathname.split("/").filter(Boolean)[1] ?? "my-requests";
  const [requests, setRequests] = useState<LeaveRequest[]>([]);
  const [policies, setPolicies] = useState<LeavePolicy[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [category, setCategory] = useState<string | null>("CL");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [purpose, setPurpose] = useState("");
  const [half, setHalf] = useState<string | null>("none");
  const [stationLeave, setStationLeave] = useState(false);
  const [stationDetails, setStationDetails] = useState("");
  const [requiresSubstitute, setRequiresSubstitute] = useState(false);
  const [substituteId, setSubstituteId] = useState("");

  const titles: Record<string, string> = {
    "my-requests": "My Leave Requests",
    apply: "Apply for Leave",
    review: "Leave Review Queue",
    admin: "ELM Administration",
  };
  const title = titles[section] ?? "Employee Leave Management";

  async function loadData() {
    setLoading(true);
    setError("");
    try {
      if (section === "admin") {
        const response = await http.get<LeavePolicy[]>("/elm/policies");
        setPolicies(response.data);
      } else {
        const response = await http.get<ListResponse<LeaveRequest>>("/elm/leave-requests");
        setRequests(response.data.results ?? []);
      }
    } catch (err) {
      setError(getError(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
    // The URL determines which ELM endpoint the page loads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);

  async function submitLeave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await http.post("/elm/leave-requests", {
        category,
        start_date: startDate,
        end_date: endDate,
        cl_half: half ?? "none",
        purpose,
        station_leave: stationLeave,
        station_leave_details: stationDetails,
        requires_substitute: requiresSubstitute,
        substitute_user_id: requiresSubstitute && substituteId ? Number(substituteId) : null,
      });
      setNotice("Leave application submitted.");
      setPurpose("");
      await loadData();
    } catch (err) {
      setError(getError(err));
    } finally {
      setBusy(false);
    }
  }

  async function decide(requestId: number, decision: "approve" | "reject") {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await http.post(`/elm/leave-requests/${requestId}/decision`, { decision, note: "" });
      setNotice(`Decision recorded for request EL-${requestId}.`);
      await loadData();
    } catch (err) {
      setError(getError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Container size="xl" py="md">
      <PageHeader title={title} subtitle="Fusion ERP · Employee Leave Management" />
      <Stack gap="md">
        {error && <Alert color="red" title="Unable to load ELM">{error}</Alert>}
        {notice && <Alert color="green" title="ELM">{notice}</Alert>}
        {section === "apply" && (
          <Card withBorder padding="lg">
            <form onSubmit={submitLeave}>
              <Stack gap="sm">
                <Select label="Leave category" data={categories} value={category} onChange={setCategory} required />
                <Group grow>
                  <TextInput type="date" label="Start date" value={startDate} onChange={(e) => setStartDate(e.currentTarget.value)} required />
                  <TextInput type="date" label="End date" value={endDate} onChange={(e) => setEndDate(e.currentTarget.value)} required />
                </Group>
                {category === "CL" && (
                  <Select label="CL day portion" data={[{ value: "none", label: "Full day" }, { value: "first", label: "First half" }, { value: "second", label: "Second half" }]} value={half} onChange={setHalf} />
                )}
                <Textarea label="Purpose / reason" value={purpose} onChange={(e) => setPurpose(e.currentTarget.value)} maxLength={1000} required />
                <Checkbox label="Station Leave required" checked={stationLeave} onChange={(e) => setStationLeave(e.currentTarget.checked)} />
                {stationLeave && <Textarea label="Station Leave details" value={stationDetails} onChange={(e) => setStationDetails(e.currentTarget.value)} required />}
                <Checkbox label="Nominate a substitute / responsibility holder" checked={requiresSubstitute} onChange={(e) => setRequiresSubstitute(e.currentTarget.checked)} />
                {requiresSubstitute && <TextInput label="Substitute user ID" inputMode="numeric" value={substituteId} onChange={(e) => setSubstituteId(e.currentTarget.value)} required />}
                <Group justify="flex-end"><Button type="submit" loading={busy}>Submit application</Button></Group>
              </Stack>
            </form>
          </Card>
        )}
        {section === "admin" && (
          <Card withBorder padding="lg">
            <Title order={3} mb="sm">Leave policies</Title>
            {loading ? <Loader /> : policies.length ? (
              <Table striped highlightOnHover>
                <Table.Thead><Table.Tr><Table.Th>Category</Table.Th><Table.Th>Annual entitlement</Table.Th><Table.Th>Scope</Table.Th><Table.Th>Status</Table.Th></Table.Tr></Table.Thead>
                <Table.Tbody>{policies.map((policy) => (
                  <Table.Tr key={policy.id}>
                    <Table.Td>{policy.category}</Table.Td><Table.Td>{policy.annual_entitlement} days</Table.Td><Table.Td>{policy.employee_scope}</Table.Td>
                    <Table.Td><Badge color={policy.enabled ? "green" : "gray"}>{policy.enabled ? "Enabled" : "Disabled"}</Badge></Table.Td>
                  </Table.Tr>
                ))}</Table.Tbody>
              </Table>
            ) : <Text c="dimmed">No policies returned by the ELM API.</Text>}
          </Card>
        )}
        {(section === "my-requests" || section === "review") && (
          <>
            <Group justify="space-between"><Text c="dimmed">{section === "review" ? "Requests available to your role" : "Your submitted leave requests"}</Text><Button variant="light" onClick={() => void loadData()} loading={loading}>Refresh</Button></Group>
            {loading ? <Loader /> : requests.length ? requests.map((request) => (
              <Card key={request.id} withBorder padding="md">
                <Group justify="space-between" align="flex-start">
                  <Stack gap={4}>
                    <Title order={4}>EL-{request.id} · {request.category}</Title>
                    <Text size="sm">{request.start_date} – {request.end_date} · {request.requested_days} day(s)</Text>
                    <Text size="sm">{request.purpose}</Text>
                  </Stack>
                  <Badge>{request.status.replaceAll("_", " ")}</Badge>
                </Group>
                {section === "review" && <Group mt="md" justify="flex-end"><Button size="xs" loading={busy} onClick={() => void decide(request.id, "approve")}>Approve</Button><Button size="xs" color="red" variant="light" loading={busy} onClick={() => void decide(request.id, "reject")}>Reject</Button></Group>}
              </Card>
            )) : <Text c="dimmed">No leave requests to display.</Text>}
          </>
        )}
      </Stack>
    </Container>
  );
}
