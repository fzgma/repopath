#include "greeting.hpp"

int main() {
    demo::Greeter greeter;
    return greeter.message().empty();
}
