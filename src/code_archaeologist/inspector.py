"""AST Inspector module using Tree-Sitter for Java parsing.

Extracts class metadata, dependency injection annotations, methods,
invocations, and cyclomatic complexity from legacy Java source files
without requiring an LLM or compiler execution.
"""

from pathlib import Path

import tree_sitter
import tree_sitter_java

from code_archaeologist.models import (
    FieldInfo,
    JavaClassInspection,
    MethodInfo,
    ParameterInfo,
)

# Anotações comuns que indicam dependências fornecidas pelo container Java.
# Campos com uma dessas anotações podem virar mocks nos testes gerados.
INJECTION_ANNOTATION_PREFIXES = (
    "@Autowired",
    "@Inject",
    "@Resource",
    "@EJB",
    "@PersistenceContext",
)

# Nós da AST que representam decisões e aumentam a complexidade ciclomática.
BRANCH_NODE_TYPES = {
    "if_statement",
    "for_statement",
    "enhanced_for_statement",
    "while_statement",
    "do_statement",
    "catch_clause",
    "conditional_expression",
    "switch_block_statement_group",
    "switch_rule",
}

# Palavras-chave usadas para identificar visibilidade e comportamento do método.
MODIFIER_KEYWORDS = {
    "public",
    "private",
    "protected",
    "static",
    "final",
    "synchronized",
    "abstract",
    "transient",
    "volatile",
}


class CodeInspector:
    """Analisa a estrutura de arquivos Java sem executar o código-fonte."""

    def __init__(self) -> None:
        # A gramática Java informa ao Tree-sitter como transformar texto em AST.
        self.language = tree_sitter.Language(tree_sitter_java.language())
        self.parser = tree_sitter.Parser(self.language)

    def inspect_file(self, file_path: str | Path) -> JavaClassInspection:
        """Lê um arquivo Java e devolve seus metadados estruturais."""
        path = Path(file_path)
        # Falha cedo com uma mensagem clara em vez de deixar a leitura gerar erro confuso.
        if not path.is_file():
            raise FileNotFoundError(f"Java source file not found: {file_path}")

        # UTF-8 é o padrão mais comum em projetos Java; caracteres inválidos são substituídos.
        code = path.read_text(encoding="utf-8", errors="replace")
        return self.inspect_code(code, file_path=str(path))

    def inspect_code(self, source_code: str, file_path: str | None = None) -> JavaClassInspection:
        """Converte código Java em AST e extrai informações da classe principal."""
        source_bytes = source_code.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        root = tree.root_node

        # Package e imports ficam no nível superior da árvore, junto das declarações.
        package_name: str | None = None
        imports: list[str] = []
        primary_class_node: tree_sitter.Node | None = None

        for child in root.children:
            if child.type == "package_declaration":
                package_name = self._extract_package(child, source_bytes)
            elif child.type == "import_declaration":
                imp = self._extract_text(child, source_bytes).strip()
                if imp:
                    imports.append(imp)
            elif child.type == "class_declaration":
                # Guarda primeira classe; se houver várias, prefere a classe pública.
                if primary_class_node is None:
                    primary_class_node = child
                else:
                    modifiers = self._get_child_by_type(child, "modifiers")
                    if modifiers and "public" in self._extract_text(modifiers, source_bytes):
                        primary_class_node = child

        if primary_class_node is None:
            # Mantém um resultado válido mesmo quando o arquivo não contém uma classe.
            return JavaClassInspection(
                file_path=file_path,
                package_name=package_name,
                imports=imports,
                class_name="UnknownClass",
                class_annotations=[],
                interfaces=[],
                super_class=None,
                fields=[],
                methods=[],
            )

        return self._extract_class_data(
            class_node=primary_class_node,
            source_bytes=source_bytes,
            package_name=package_name,
            imports=imports,
            file_path=file_path,
        )

    def _extract_class_data(
        self,
        class_node: tree_sitter.Node,
        source_bytes: bytes,
        package_name: str | None,
        imports: list[str],
        file_path: str | None,
    ) -> JavaClassInspection:
        # Lê nome, herança e interfaces diretamente dos campos da AST.
        name_node = class_node.child_by_field_name("name")
        class_name = self._extract_text(name_node, source_bytes) if name_node else "UnknownClass"

        # O nó superclass inclui a palavra-chave "extends"; removemos para guardar só o tipo.
        super_class: str | None = None
        superclass_node = self._get_child_by_type(class_node, "superclass")
        if superclass_node:
            sc_text = self._extract_text(superclass_node, source_bytes).strip()
            if sc_text.startswith("extends"):
                sc_text = sc_text[7:].strip()
            super_class = sc_text

        # Interfaces podem aparecer agrupadas em type_list ou como nó individual.
        interfaces: list[str] = []
        super_interfaces_node = self._get_child_by_type(class_node, "super_interfaces")
        if super_interfaces_node:
            type_list = self._get_child_by_type(super_interfaces_node, "type_list")
            if type_list:
                for iface_node in type_list.children:
                    if iface_node.type not in (",", "type_list"):
                        t = self._extract_text(iface_node, source_bytes).strip()
                        if t:
                            interfaces.append(t)
            else:
                raw_interfaces = self._extract_text(super_interfaces_node, source_bytes).strip()
                if raw_interfaces.startswith("implements"):
                    raw_interfaces = raw_interfaces[10:].strip()
                interfaces = [i.strip() for i in raw_interfaces.split(",") if i.strip()]

        # Anotações da classe costumam estar junto dos modificadores na AST.
        class_annotations: list[str] = []
        modifiers_node = self._get_child_by_type(class_node, "modifiers")
        if modifiers_node:
            class_annotations = self._extract_annotations(modifiers_node, source_bytes)

        # Percorre membros do corpo e delega cada campo/método ao parser específico.
        fields: list[FieldInfo] = []
        methods: list[MethodInfo] = []

        body_node = self._get_child_by_type(class_node, "class_body") or class_node.child_by_field_name("body")
        if body_node:
            for member in body_node.children:
                if member.type == "field_declaration":
                    field = self._parse_field(member, source_bytes)
                    if field:
                        fields.append(field)
                elif member.type == "method_declaration":
                    method = self._parse_method(member, source_bytes)
                    if method:
                        methods.append(method)

        return JavaClassInspection(
            file_path=file_path,
            package_name=package_name,
            imports=imports,
            class_name=class_name,
            class_annotations=class_annotations,
            interfaces=interfaces,
            super_class=super_class,
            fields=fields,
            methods=methods,
        )

    def _parse_field(self, field_node: tree_sitter.Node, source_bytes: bytes) -> FieldInfo | None:
        # Uma declaração simples contém tipo e declarador (nome, possivelmente inicializado).
        type_node = field_node.child_by_field_name("type")
        declarator_node = field_node.child_by_field_name("declarator")

        if not type_node or not declarator_node:
            return None

        field_type = self._extract_text(type_node, source_bytes).strip()
        name_node = declarator_node.child_by_field_name("name")
        field_name = self._extract_text(name_node or declarator_node, source_bytes).strip()

        annotations: list[str] = []
        modifiers_node = self._get_child_by_type(field_node, "modifiers")
        if modifiers_node:
            annotations = self._extract_annotations(modifiers_node, source_bytes)

        # Compara anotações do campo com as conhecidas de injeção de dependência.
        is_injected = any(
            any(ann.startswith(prefix) for prefix in INJECTION_ANNOTATION_PREFIXES)
            for ann in annotations
        )

        return FieldInfo(
            name=field_name,
            type=field_type,
            annotations=annotations,
            is_injected=is_injected,
        )

    def _parse_method(self, method_node: tree_sitter.Node, source_bytes: bytes) -> MethodInfo | None:
        # Extrai assinatura primeiro; sem nome, nó não representa método utilizável.
        name_node = method_node.child_by_field_name("name")
        if not name_node:
            return None

        method_name = self._extract_text(name_node, source_bytes).strip()

        type_node = method_node.child_by_field_name("type")
        return_type = self._extract_text(type_node, source_bytes).strip() if type_node else "void"

        modifiers: list[str] = []
        annotations: list[str] = []
        modifiers_node = self._get_child_by_type(method_node, "modifiers")
        if modifiers_node:
            # A AST reúne anotações e modificadores no mesmo nó; guardamos separadamente.
            annotations = self._extract_annotations(modifiers_node, source_bytes)
            for ch in modifiers_node.children:
                if ch.type in MODIFIER_KEYWORDS:
                    modifiers.append(ch.type)

        parameters: list[ParameterInfo] = []
        params_node = method_node.child_by_field_name("parameters")
        if params_node:
            # Cada parâmetro fornece tipo, nome e, quando houver, anotações próprias.
            for param in params_node.children:
                if param.type == "formal_parameter":
                    p_type_node = param.child_by_field_name("type")
                    p_name_node = param.child_by_field_name("name")
                    if p_type_node and p_name_node:
                        p_type = self._extract_text(p_type_node, source_bytes).strip()
                        p_name = self._extract_text(p_name_node, source_bytes).strip()
                        p_ann: list[str] = []
                        p_mods = self._get_child_by_type(param, "modifiers")
                        if p_mods:
                            p_ann = self._extract_annotations(p_mods, source_bytes)
                        parameters.append(ParameterInfo(name=p_name, type=p_type, annotations=p_ann))

        throws_exceptions: list[str] = []
        throws_node = self._get_child_by_type(method_node, "throws")
        if throws_node:
            # Ignora vírgulas e palavra-chave "throws"; mantém apenas os tipos de exceção.
            for ex_node in throws_node.children:
                if ex_node.type not in ("throws", ","):
                    ex_text = self._extract_text(ex_node, source_bytes).strip()
                    if ex_text:
                        throws_exceptions.append(ex_text)

        # Métodos abstratos não têm corpo; nesses casos body_source e chamadas ficam vazios.
        body_node = method_node.child_by_field_name("body") or self._get_child_by_type(method_node, "block")
        body_source = self._extract_text(body_node, source_bytes) if body_node else ""
        invoked_methods = self._extract_invocations(body_node, source_bytes) if body_node else []
        complexity = self._calculate_cyclomatic_complexity(body_node, source_bytes) if body_node else 1

        return MethodInfo(
            name=method_name,
            return_type=return_type,
            modifiers=modifiers,
            parameters=parameters,
            annotations=annotations,
            throws_exceptions=throws_exceptions,
            body_source=body_source,
            invoked_methods=invoked_methods,
            cyclomatic_complexity=complexity,
        )

    def _extract_annotations(self, modifiers_node: tree_sitter.Node, source_bytes: bytes) -> list[str]:
        """Retorna texto de cada anotação encontrada em um nó de modificadores."""
        annotations: list[str] = []
        for child in modifiers_node.children:
            if child.type in ("annotation", "marker_annotation"):
                ann_text = self._extract_text(child, source_bytes).strip()
                if ann_text:
                    annotations.append(ann_text)
        return annotations

    def _extract_invocations(self, body_node: tree_sitter.Node, source_bytes: bytes) -> list[str]:
        """Lista chamadas de método no corpo, sem repetir chamadas idênticas."""
        invocations: list[str] = []
        seen: set[str] = set()

        def walk(node: tree_sitter.Node) -> None:
            if node.type == "method_invocation":
                inv_text = self._extract_text(node, source_bytes).strip()
                if inv_text and inv_text not in seen:
                    seen.add(inv_text)
                    invocations.append(inv_text)
            # Visita toda a subárvore para incluir chamadas aninhadas, como foo().bar().
            for child in node.children:
                walk(child)

        walk(body_node)
        return invocations

    def _calculate_cyclomatic_complexity(self, body_node: tree_sitter.Node, source_bytes: bytes) -> int:
        """Conta caminhos independentes: começa em 1 e soma decisões e operadores lógicos."""
        complexity = 1

        def walk(node: tree_sitter.Node) -> None:
            nonlocal complexity
            if node.type in BRANCH_NODE_TYPES:
                complexity += 1
            elif node.type == "binary_expression":
                # Cada && ou || adiciona um caminho possível à decisão.
                op_node = node.child_by_field_name("operator")
                if op_node:
                    op_text = self._extract_text(op_node, source_bytes).strip()
                    if op_text in ("&&", "||"):
                        complexity += 1
            for child in node.children:
                walk(child)

        walk(body_node)
        return complexity

    def _extract_package(self, package_node: tree_sitter.Node, source_bytes: bytes) -> str | None:
        """Extrai nome qualificado do pacote, por exemplo com.exemplo.servico."""
        for child in package_node.children:
            if child.type in ("scoped_identifier", "identifier"):
                return self._extract_text(child, source_bytes).strip()
        return None

    def _get_child_by_type(self, node: tree_sitter.Node, child_type: str) -> tree_sitter.Node | None:
        """Procura filho direto pelo tipo, sem percorrer níveis internos da AST."""
        for child in node.children:
            if child.type == child_type:
                return child
        return None

    def _extract_text(self, node: tree_sitter.Node, source_bytes: bytes) -> str:
        """Recupera trecho original usando posições em bytes fornecidas pelo Tree-sitter."""
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
