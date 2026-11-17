"""Domain and data transfer models for Code Archaeologist.

These models serve dual purposes:
1. Representing static AST analysis extracted from legacy Java files.
2. Defining strict Pydantic schemas for LLM reasoning, structured generation,
   Gherkin rule extraction, test scaffolding, and architecture diagrams.
"""

from enum import Enum

from pydantic import BaseModel, Field

# ==============================================================================
# 1. AST Static Inspection Models (Fase 1)
# ==============================================================================

class ParameterInfo(BaseModel):
    """Metadata about a method parameter."""
    name: str = Field(description="Parameter name, e.g. 'orderId'")
    type: str = Field(description="Parameter type, e.g. 'Long', 'CustomerDTO'")
    annotations: list[str] = Field(default_factory=list, description="Annotations like @NotNull, @Valid")


class FieldInfo(BaseModel):
    """Metadata about a class field / dependency."""
    name: str = Field(description="Field variable name, e.g. 'userRepository'")
    type: str = Field(description="Field type, e.g. 'UserRepository', 'PaymentGateway'")
    annotations: list[str] = Field(
        default_factory=list,
        description="Field annotations, e.g. ['@Autowired', '@Inject', '@Resource']"
    )
    is_injected: bool = Field(
        default=False,
        description="True if annotated with dependency injection (@Autowired, @Inject, etc.)"
    )


class MethodInfo(BaseModel):
    """Metadata about a method in a Java class."""
    name: str = Field(description="Method name, e.g. 'calculateTaxes'")
    return_type: str = Field(default="void", description="Return type, e.g. 'BigDecimal'")
    modifiers: list[str] = Field(default_factory=list, description="Modifiers: public, private, static, etc.")
    parameters: list[ParameterInfo] = Field(default_factory=list, description="List of parameters")
    annotations: list[str] = Field(default_factory=list, description="Method annotations, e.g. @Transactional")
    throws_exceptions: list[str] = Field(default_factory=list, description="Declared throws clauses")
    body_source: str = Field(default="", description="Raw source code of the method body")
    invoked_methods: list[str] = Field(
        default_factory=list,
        description="Calls to dependencies or other methods detected in the body"
    )
    cyclomatic_complexity: int = Field(default=1, description="McCabe cyclomatic complexity score")

    @property
    def is_public(self) -> bool:
        return "public" in self.modifiers

    @property
    def signature(self) -> str:
        params = ", ".join(f"{p.type} {p.name}" for p in self.parameters)
        return f"{self.return_type} {self.name}({params})"


class JavaClassInspection(BaseModel):
    """Complete AST inspection metadata of a Java source file."""
    file_path: str | None = Field(default=None, description="Absolute or relative path to the .java file")
    package_name: str | None = Field(default=None, description="Java package, e.g. 'com.company.service'")
    imports: list[str] = Field(default_factory=list, description="All import statements")
    class_name: str = Field(description="Name of the class, e.g. 'OrderService'")
    class_annotations: list[str] = Field(
        default_factory=list,
        description="Class annotations, e.g. ['@Service', '@Transactional']"
    )
    interfaces: list[str] = Field(default_factory=list, description="Implemented interfaces")
    super_class: str | None = Field(default=None, description="Extended superclass")
    fields: list[FieldInfo] = Field(default_factory=list, description="All declared fields")
    methods: list[MethodInfo] = Field(default_factory=list, description="All declared methods")

    @property
    def injected_dependencies(self) -> list[FieldInfo]:
        """Returns only fields that represent injected dependencies (candidates for @Mock)."""
        return [f for f in self.fields if f.is_injected]

    @property
    def public_methods(self) -> list[MethodInfo]:
        """Returns only public methods (primary targets for testing and business rules)."""
        return [m for m in self.methods if m.is_public]


# ==============================================================================
# 2. Business Archaeology Models (BDD / Gherkin) (Fase 2)
# ==============================================================================

class GherkinScenario(BaseModel):
    """Individual BDD scenario."""
    title: str = Field(description="Descriptive title of the scenario")
    given: list[str] = Field(description="Initial context / preconditions (Dado)")
    when: list[str] = Field(description="Actions / triggers (Quando)")
    then: list[str] = Field(description="Expected outcomes / assertions (Então)")


class BusinessRule(BaseModel):
    """Extracted business rule with edge cases and exceptions."""
    id: str = Field(description="Rule identifier, e.g. 'REG-001'")
    title: str = Field(description="Brief title of the rule")
    description: str = Field(description="Detailed business explanation for domain analysts")
    edge_cases: list[str] = Field(default_factory=list, description="Boundary conditions, edge cases, special limits")
    triggered_exceptions: list[str] = Field(
        default_factory=list,
        description="Exceptions thrown when this rule is violated"
    )
    scenarios: list[GherkinScenario] = Field(
        default_factory=list,
        description="BDD Gherkin scenarios representing this rule"
    )


class BusinessArchaeologyReport(BaseModel):
    """Complete Business Rules excavation report."""
    target_class: str = Field(description="Target Java class name")
    executive_summary: str = Field(description="High-level overview of what this class/service does in the business domain")
    implicit_assumptions: list[str] = Field(
        default_factory=list,
        description="Hidden assumptions found in the code (e.g. 'Currency is always BRL', 'Tax rate hardcoded to 15%')"
    )
    rules: list[BusinessRule] = Field(default_factory=list, description="List of extracted business rules")


# ==============================================================================
# 3. Architecture & Sequence Flow Models (Mermaid.js) (Fase 2)
# ==============================================================================

class SequenceStep(BaseModel):
    """Step in a sequence diagram between architectural components."""
    from_component: str = Field(description="Source participant, e.g. 'OrderController'")
    to_component: str = Field(description="Target participant, e.g. 'OrderService'")
    message: str = Field(description="Method call or message sent, e.g. 'processOrder(orderDto)'")
    response: str | None = Field(default=None, description="Return message or response")
    notes: str | None = Field(default=None, description="Contextual note or business logic detail")


class ArchitectureFlow(BaseModel):
    """Sequence diagram and layered flow mapping."""
    title: str = Field(description="Flow title, e.g. 'Fluxo de Processamento de Pedidos'")
    participants: list[str] = Field(description="List of architectural layers/components involved")
    steps: list[SequenceStep] = Field(default_factory=list, description="Ordered sequence steps")
    mermaid_code: str = Field(
        description="Ready-to-render Mermaid.js sequence diagram (starts with 'sequenceDiagram')"
    )


# ==============================================================================
# 4. Unit Test Scaffolding & Self-Correction Models (Fase 2 & Fase 3)
# ==============================================================================

class MockRequirement(BaseModel):
    """Specification of a dependency to mock with Mockito."""
    field_name: str = Field(description="Name of the mock variable, e.g. 'paymentGateway'")
    class_type: str = Field(description="Type to mock, e.g. 'PaymentGateway'")
    stubbed_methods: list[str] = Field(
        default_factory=list,
        description="Methods that need `when(...).thenReturn(...)`"
    )


class TestScenario(BaseModel):
    """Individual unit test method to generate."""
    method_name: str = Field(description="JUnit test method name, e.g. 'shouldThrowExceptionWhenBalanceIsInsufficient'")
    description: str = Field(description="What this test asserts")
    is_happy_path: bool = Field(default=True, description="True if happy path, False if edge case / exception flow")
    target_method: str = Field(description="Name of the service method under test")


class UnitTestSuite(BaseModel):
    """Generated JUnit 5 + Mockito test suite with self-correction metadata."""
    test_class_name: str = Field(description="Generated test class name, e.g. 'OrderServiceTest'")
    target_class_name: str = Field(description="Class being tested, e.g. 'OrderService'")
    imports: list[str] = Field(default_factory=list, description="Required test imports")
    mocks: list[MockRequirement] = Field(default_factory=list, description="Mocks configured with @Mock")
    test_scenarios: list[TestScenario] = Field(default_factory=list, description="Planned test scenarios")
    java_code: str = Field(description="Complete compilable Java test source code (JUnit 5 + Mockito)")

    # Self-correction loop metadata
    compilation_passed: bool = Field(default=False, description="Whether mvn test-compile succeeded")
    correction_iterations: int = Field(default=0, description="Number of auto-repair iterations performed")
    compiler_errors: list[str] = Field(default_factory=list, description="Errors captured from compiler if failed")


# ==============================================================================
# 5. Technical Debt & Code Audit Models (Fase 4)
# ==============================================================================

class SeverityEnum(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TechnicalDebtItem(BaseModel):
    """Specific technical debt finding in legacy code."""
    category: str = Field(
        description="Category: 'cyclomatic_complexity', 'swallowed_exception', 'hardcoded_sql', 'tight_coupling', etc."
    )
    severity: SeverityEnum = Field(description="Severity level")
    location: str = Field(description="Method name or line reference where issue occurs")
    description: str = Field(description="Detailed explanation of the flaw")
    recommendation: str = Field(description="Modern refactoring suggestion (e.g. pattern or modern Java construct)")


class AuditReport(BaseModel):
    """Technical debt and code quality audit report."""
    target_class: str = Field(description="Class audited")
    cyclomatic_complexity_warning: bool = Field(
        default=False,
        description="True if any method has alarmingly high complexity"
    )
    findings: list[TechnicalDebtItem] = Field(default_factory=list, description="List of detected code smells and debt")
    refactoring_summary: str = Field(description="Overall refactoring roadmap for this class")


# ==============================================================================
# 6. Consolidated Archaeology Report
# ==============================================================================

class CompleteArchaeologyArtifacts(BaseModel):
    """Bundles all excavated artifacts for export and reporting."""
    inspection: JavaClassInspection
    business_report: BusinessArchaeologyReport | None = None
    architecture_flow: ArchitectureFlow | None = None
    test_suite: UnitTestSuite | None = None
    audit_report: AuditReport | None = None
