"""Unit tests for CodeInspector (AST Java analysis)."""

import pytest

from code_archaeologist.inspector import CodeInspector

SAMPLE_LEGACY_SERVICE = """
package com.legacy.ecommerce.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import javax.inject.Inject;
import com.legacy.ecommerce.repository.OrderRepository;
import com.legacy.ecommerce.gateway.PaymentGateway;

@Service
public class OrderService extends BaseService implements IOrderService {

    @Autowired
    private OrderRepository orderRepository;

    @Inject
    private PaymentGateway paymentGateway;

    private int maxRetryAttempts = 3;

    public boolean processOrder(Long orderId, String customerId) throws OrderNotFoundException, PaymentFailedException {
        if (orderId == null || customerId == null) {
            throw new IllegalArgumentException("IDs cannot be null");
        }

        Order order = orderRepository.findById(orderId);
        if (order == null) {
            throw new OrderNotFoundException("Order not found: " + orderId);
        }

        boolean paid = paymentGateway.charge(order.getTotal());
        if (!paid) {
            throw new PaymentFailedException("Payment rejected");
        }

        order.setStatus("PAID");
        orderRepository.save(order);
        return true;
    }

    private void logExecution(String msg) {
        System.out.println(msg);
    }
}
"""


@pytest.fixture
def inspector() -> CodeInspector:
    return CodeInspector()


def test_inspect_package_and_class_metadata(inspector: CodeInspector):
    inspection = inspector.inspect_code(SAMPLE_LEGACY_SERVICE)

    assert inspection.package_name == "com.legacy.ecommerce.service"
    assert inspection.class_name == "OrderService"
    assert "@Service" in inspection.class_annotations
    assert inspection.super_class == "BaseService"
    assert "IOrderService" in inspection.interfaces
    assert len(inspection.imports) == 5


def test_inspect_injected_dependencies(inspector: CodeInspector):
    inspection = inspector.inspect_code(SAMPLE_LEGACY_SERVICE)

    # Injected fields
    injected = inspection.injected_dependencies
    assert len(injected) == 2

    repo_field = next(f for f in injected if f.name == "orderRepository")
    assert repo_field.type == "OrderRepository"
    assert repo_field.is_injected is True
    assert "@Autowired" in repo_field.annotations

    gateway_field = next(f for f in injected if f.name == "paymentGateway")
    assert gateway_field.type == "PaymentGateway"
    assert gateway_field.is_injected is True
    assert "@Inject" in gateway_field.annotations

    # Non-injected field
    retry_field = next(f for f in inspection.fields if f.name == "maxRetryAttempts")
    assert retry_field.is_injected is False


def test_inspect_methods_and_invocations(inspector: CodeInspector):
    inspection = inspector.inspect_code(SAMPLE_LEGACY_SERVICE)

    public_methods = inspection.public_methods
    assert len(public_methods) == 1

    proc_order = public_methods[0]
    assert proc_order.name == "processOrder"
    assert proc_order.return_type == "boolean"
    assert proc_order.is_public is True
    assert len(proc_order.parameters) == 2
    assert proc_order.parameters[0].name == "orderId"
    assert proc_order.parameters[0].type == "Long"

    assert "OrderNotFoundException" in proc_order.throws_exceptions
    assert "PaymentFailedException" in proc_order.throws_exceptions

    # Check method invocations detected
    invocations_str = " ".join(proc_order.invoked_methods)
    assert "orderRepository.findById" in invocations_str
    assert "paymentGateway.charge" in invocations_str
    assert "orderRepository.save" in invocations_str

    # Cyclomatic complexity: Base (1) + if (1) + || (1) + if (1) + if (1) = 5
    assert proc_order.cyclomatic_complexity >= 4


def test_empty_or_minimal_code(inspector: CodeInspector):
    inspection = inspector.inspect_code("public class Minimal {}")
    assert inspection.class_name == "Minimal"
    assert len(inspection.methods) == 0
    assert len(inspection.fields) == 0
