#!/usr/bin/env python3
"""
Performance testing for multi-provider Claude Code functionality.
Tests response times, retry behavior, and error handling across providers.
"""

import time
import statistics
from typing import List, Dict, Any
from claudecode.claude_client_factory import create_claude_client


def measure_api_call_performance(client, num_calls: int = 5) -> Dict[str, Any]:
    """Measure API call performance for a client."""
    print(f"   Testing {type(client).__name__} performance ({num_calls} calls)...")
    
    times = []
    successes = 0
    errors = []
    
    test_finding = {
        "rule": "performance-test",
        "file": "test.py",
        "line": 1,
        "severity": "MEDIUM",
        "message": "Performance test finding - should be filtered as false positive"
    }
    
    for i in range(num_calls):
        start_time = time.time()
        try:
            success, result, error = client.analyze_single_finding(test_finding)
            end_time = time.time()
            
            call_time = end_time - start_time
            times.append(call_time)
            
            if success:
                successes += 1
            else:
                errors.append(error)
                
        except Exception as e:
            end_time = time.time()
            times.append(end_time - start_time)
            errors.append(str(e))
    
    return {
        "client_type": type(client).__name__,
        "total_calls": num_calls,
        "successful_calls": successes,
        "failed_calls": len(errors),
        "success_rate": (successes / num_calls) * 100,
        "average_time": statistics.mean(times) if times else 0,
        "median_time": statistics.median(times) if times else 0,
        "min_time": min(times) if times else 0,
        "max_time": max(times) if times else 0,
        "errors": errors[:3]  # Show first 3 errors
    }


def test_retry_behavior(client) -> Dict[str, Any]:
    """Test retry behavior with invalid requests."""
    print(f"   Testing {type(client).__name__} retry behavior...")
    
    # Test with an invalid prompt that should trigger retries
    start_time = time.time()
    try:
        success, result, error = client.call_with_retry(
            prompt="",  # Empty prompt should fail
            max_tokens=1
        )
        end_time = time.time()
        
        return {
            "client_type": type(client).__name__,
            "success": success,
            "total_time": end_time - start_time,
            "error": error[:100] if error else None  # Truncate long errors
        }
    except Exception as e:
        end_time = time.time()
        return {
            "client_type": type(client).__name__,
            "success": False,
            "total_time": end_time - start_time,
            "error": str(e)[:100]
        }


def test_concurrent_calls(client, num_concurrent: int = 3) -> Dict[str, Any]:
    """Test concurrent API calls (simulated with sequential calls)."""
    print(f"   Testing {type(client).__name__} concurrent behavior...")
    
    import concurrent.futures
    
    test_finding = {
        "rule": "concurrent-test",
        "file": "concurrent.py",
        "line": i,
        "severity": "LOW",
        "message": f"Concurrent test finding #{i}"
    }
    
    def make_call(call_id):
        finding = test_finding.copy()
        finding["line"] = call_id
        finding["message"] = f"Concurrent test finding #{call_id}"
        
        start_time = time.time()
        try:
            success, result, error = client.analyze_single_finding(finding)
            end_time = time.time()
            return {
                "call_id": call_id,
                "success": success,
                "time": end_time - start_time,
                "error": error if error else None
            }
        except Exception as e:
            end_time = time.time()
            return {
                "call_id": call_id,
                "success": False, 
                "time": end_time - start_time,
                "error": str(e)
            }
    
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_concurrent) as executor:
        futures = [executor.submit(make_call, i) for i in range(num_concurrent)]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
    
    total_time = time.time() - start_time
    successful_calls = sum(1 for r in results if r["success"])
    
    return {
        "client_type": type(client).__name__,
        "concurrent_calls": num_concurrent,
        "successful_calls": successful_calls,
        "total_time": total_time,
        "average_call_time": statistics.mean([r["time"] for r in results]),
        "success_rate": (successful_calls / num_concurrent) * 100
    }


def run_performance_tests():
    """Run performance tests for all available providers."""
    print("🚀 Multi-Provider Performance Testing")
    print("=" * 50)
    
    try:
        # Create client for current configuration
        client = create_claude_client()
        print(f"Testing with: {type(client).__name__}")
        
        # Test basic performance
        print("\n1. API Call Performance:")
        perf_results = measure_api_call_performance(client, num_calls=3)
        print(f"   Success rate: {perf_results['success_rate']:.1f}%")
        print(f"   Average time: {perf_results['average_time']:.2f}s")
        print(f"   Time range: {perf_results['min_time']:.2f}s - {perf_results['max_time']:.2f}s")
        
        if perf_results['errors']:
            print(f"   Errors: {perf_results['errors'][0][:50]}...")
        
        # Test retry behavior
        print("\n2. Retry Behavior:")
        retry_results = test_retry_behavior(client)
        print(f"   Retry success: {retry_results['success']}")
        print(f"   Total retry time: {retry_results['total_time']:.2f}s")
        
        # Test concurrent calls
        print("\n3. Concurrent Calls:")
        concurrent_results = test_concurrent_calls(client, num_concurrent=2)
        print(f"   Success rate: {concurrent_results['success_rate']:.1f}%")
        print(f"   Total time: {concurrent_results['total_time']:.2f}s")
        print(f"   Avg per call: {concurrent_results['average_call_time']:.2f}s")
        
        return {
            "performance": perf_results,
            "retry": retry_results, 
            "concurrent": concurrent_results
        }
        
    except Exception as e:
        print(f"❌ Performance testing failed: {e}")
        return None


if __name__ == "__main__":
    results = run_performance_tests()
    
    if results:
        print("\n✅ Performance testing complete!")
        print("\n📊 Summary:")
        print(f"   API Success Rate: {results['performance']['success_rate']:.1f}%")
        print(f"   Average Response Time: {results['performance']['average_time']:.2f}s")
        print(f"   Concurrent Success Rate: {results['concurrent']['success_rate']:.1f}%")
    else:
        print("❌ Performance testing failed")
