package com.example.service;

import com.example.repository.CustomerRepository;
import java.util.Optional;

@Service
public class SampleService {
    @Autowired
    private CustomerRepository customerRepository;

    private int lookupCount;

    public Optional<Customer> findCustomer(Long id) {
        if (id == null || id <= 0) {
            throw new IllegalArgumentException("id must be positive");
        }
        lookupCount++;
        return customerRepository.findById(id);
    }

    private void resetCount() {
        lookupCount = 0;
    }
}
