"""
Design (plan §8.4): a data contract for every output, and the register of suspected defects.

``contract`` builds each output's contract from the legacy DDL and a profile of the golden
output, with the Contract agent's description of the grain, and checks what H2 enforces;
``defects`` collects suspected legacy bugs and measures their impact on golden data.
"""
