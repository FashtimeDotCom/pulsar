import sys
import io
import logging
from inspect import istraceback

from pulsar import is_failure, CLEAR_ERRORS, make_async, get_actor, async
from pulsar.utils.pep import pickle


__all__ = ['TestRequest']


LOGGER = logging.getLogger('pulsar.test')

def test_method(cls, method):
    try:
        return cls(method)
    except ValueError:
        return None


class SequentialConsumer(object):
    
    def __init__(self, gen, handle_failure=None):
        self.request_loop = get_request_loop()
        self.errors = Failure()
        self.gen = gen
        self.handle_failure = handle_failure
        
    def _resume(self, result):
        self.request_loop.add_soon_threadsafe(self.consume, result)
        #TODO: Do we need to return?
        return result
        
    def consume(self, last_result=None):
        try:
            result = next(self.gen)
        except StopIteration:
            pass
        except Exception as e:
            result = e
        else:
            result = maybe_async(result)
            if is_async(result):
                result.add_both(self._resume)
                return self.request_loop.call_soon_threadsafe(self._consume)
        result = as_failure(result)
        if is_failure(result):
            result = self.handle_failure(failure)
            if is_failure(result):
                return result
        return self.consume(result)
        
    def handle_failure(self, failure):
        self.errors.append(failure)
        

def test_generator(f):
    def _(self, test, *args):
        runner = self.runner
        handle_failure = partial(self.add_failure(test, runner)) 
        gen = f(self, *args)
        tasks = SequentialConsumer(gen, handle_failure)
        return tasks.consume()
    return _

        

class TestRequest(object):
    '''A class which wraps a test case class and runs all its test functions

.. attribute:: testcls

    A :class:`unittest.TestCase` class to be run on this request.

.. attribute:: tag

    A string indicating the tag associated with :attr:`testcls`.
'''
    def __init__(self, testcls, tag):
        self.testcls = testcls
        self.tag = tag

    def __repr__(self):
        return self.testcls.__name__
    __str__ = __repr__

    def start(self):
        '''Run all test functions from the :attr:`testcls` using the
following algorithm:

* Run the class method ``setUpClass`` of :attr:`testcls` if defined.
* Call :meth:`run_test` for each test functions in :attr:`testcls`
* Run the class method ``tearDownClass`` of :attr:`testcls` if defined.
'''
        # Reset the runner
        worker = get_actor()
        worker.app.local.pop('runner')
        runner = worker.app.runner
        testcls = self.testcls
        if not isinstance(testcls, type):
            testcls = testcls()
        testcls.tag = self.tag
        testcls.cfg = worker.cfg
        LOGGER.debug('Testing %s', self)
        all_tests = runner.loadTestsFromTestCase(testcls)
        run_test_function = runner.run_test_function
        if all_tests.countTestCases():
            skip_tests = getattr(testcls, "__unittest_skip__", False)
            should_stop = False
            test_cls = test_method(testcls, 'setUpClass')
            if test_cls and not skip_tests:
                outcome = run_test_function(testcls,
                                            getattr(testcls,'setUpClass'))
                yield outcome
                should_stop = self.add_failure(test_cls, runner, outcome.result)
            if not should_stop:
                # Loop over all test cases in class
                for test in all_tests:
                    yield self.run_test(test, runner)
            test_cls = test_method(testcls, 'tearDownClass')
            if test_cls and not skip_tests:
                outcome = run_test_function(testcls,getattr(testcls,
                                                        'tearDownClass'))
                yield outcome
                self.add_failure(test_cls, runner, outcome.result)
            # Clear errors
            yield CLEAR_ERRORS
        # send runner result to monitor
        LOGGER.debug('Sending %s results back to monitor', self)
        worker.send('monitor', 'test_result', testcls.tag,
                    testcls.__name__, runner.result)

    def run_test(self, test, runner):
        '''\
Run a *test* function using the following algorithm

* Run :meth:`_pre_setup` method if available in :attr:`testcls`.
* Run :meth:`setUp` method in :attr:`testcls`.
* Run the test function.
* Run :meth:`tearDown` method in :attr:`testcls`.
* Run :meth:`_post_teardown` method if available in :attr:`testcls`.
'''
        try:
            success = True
            runner.startTest(test)
            run_test_function = runner.run_test_function
            testMethod = getattr(test, test._testMethodName)
            if (getattr(test.__class__, "__unittest_skip__", False) or
                getattr(testMethod, "__unittest_skip__", False)):
                reason = (getattr(test.__class__,
                                  '__unittest_skip_why__', '') or
                          getattr(testMethod,
                                  '__unittest_skip_why__', ''))
                runner.addSkip(test, reason)
                raise StopIteration()
            # _pre_setup function if available
            if hasattr(test,'_pre_setup'):
                outcome = run_test_function(test, test._pre_setup)
                yield outcome
                success = not self.add_failure(test, runner, outcome.result)
            # _setup function if available
            if success:
                outcome = run_test_function(test, test.setUp)
                yield outcome
                if not self.add_failure(test, runner, outcome.result):
                    # Here we perform the actual test
                    outcome = run_test_function(test, testMethod)
                    yield outcome
                    success = not self.add_failure(test, runner, outcome.result)
                    if success:
                        test.result = outcome.result
                    outcome = run_test_function(test, test.tearDown)
                    yield outcome
                    if self.add_failure(test, runner, outcome.result):
                        success = False
                else:
                    success = False
            # _post_teardown
            if hasattr(test,'_post_teardown'):
                outcome = run_test_function(test,test._post_teardown)
                yield outcome
                if self.add_failure(test, runner, outcome.result):
                    success = False
            # run the stopTest
            runner.stopTest(test)
        except StopIteration:
            success = False
        except Exception as e:
            self.add_failure(test, runner, e)
            success = False
        if success:
            runner.addSuccess(test)

    def add_failure(self, test, runner, failure):
        if is_failure(failure):
            for trace in failure:
                e = trace[1]
                try:
                    raise e
                except test.failureException:
                    runner.addFailure(test, trace)
                except Exception:
                    runner.addError(test, trace)
                return True
        else:
            return False